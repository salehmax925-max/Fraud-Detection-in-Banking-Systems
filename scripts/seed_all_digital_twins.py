"""
scripts/seed_all_digital_twins.py
===================================
Seeds ALL 2,000 synthetic users (user_0000 to user_1999) and their
transactions from creditcard.csv into PostgreSQL with:
  1. Complete transaction history (amounts, times, PCA features V1-V28)
  2. Real ML hybrid scores (XGBoost + Isolation Forest)
  3. Real SHAP explanations (via native booster pred_contribs)
  4. Real Digital Twin behavioral profiles (Welford stats, sliding windows, EMA risk)
  5. Pending review queue items for REVIEW-tier transactions

Guarantees:
  - user_0414 and ALL users from user_0000 to user_1999 have transactions and profiles.
  - No 404 "No transaction history found" for any valid synthetic user in the pool.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Setup paths
ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(BACKEND_DIR))

from ml.features import BEHAVIORAL_FEATURE_COLS, BehavioralFeatureEngine
from ml.preprocessing import add_synthetic_user_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("seed_digital_twins")

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://fraud:fraud_pass@localhost:5432/frauddb"
).replace("localhost", "127.0.0.1")

MODELS_DIR = ROOT_DIR / "models"
CSV_PATH = ROOT_DIR / "creditcard.csv"
SYNTHETIC_POOL_SIZE = 2000


def build_sampled_dataset(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Select realistic transactions for all 1,652 existing users from creditcard.csv,
    and add baseline transactions for any missing user IDs up to 2,000.
    """
    logger.info("Adding synthetic user IDs across raw dataset (%d rows)...", len(df_raw))
    df = add_synthetic_user_ids(df_raw)

    sampled_list = []
    logger.info("Sampling transactions per user (preserving all fraud cases)...")
    for uid, group in df.groupby("synthetic_user_id"):
        g_sorted = group.sort_values("Time")
        frauds = g_sorted[g_sorted["Class"] == 1]
        non_frauds = g_sorted[g_sorted["Class"] == 0]

        if len(non_frauds) > 12:
            # Pick first 6 and last 6 to capture full time span
            picked_nf = pd.concat([non_frauds.head(6), non_frauds.tail(6)])
        else:
            picked_nf = non_frauds

        combined = (
            pd.concat([frauds, picked_nf])
            .drop_duplicates(subset=["Time", "Amount"])
            .sort_values("Time")
        )
        sampled_list.append(combined)

    sampled_df = pd.concat(sampled_list).reset_index(drop=True)
    existing_uids = set(sampled_df["synthetic_user_id"])
    logger.info("Sampled %d rows across %d existing users.", len(sampled_df), len(existing_uids))

    # Fill in any missing user IDs in 0..1999 pool
    missing_uids = [
        f"user_{i:04d}" for i in range(SYNTHETIC_POOL_SIZE) if f"user_{i:04d}" not in existing_uids
    ]
    if missing_uids:
        logger.info("Synthesizing baseline transactions for %d remaining pool users...", len(missing_uids))
        template_pool = df[df["Class"] == 0].sample(n=len(missing_uids) * 3, random_state=42).copy()
        synthetic_rows = []
        idx = 0
        for uid in missing_uids:
            user_slice = template_pool.iloc[idx : idx + 3].copy()
            user_slice["synthetic_user_id"] = uid
            synthetic_rows.append(user_slice)
            idx += 3

        full_df = pd.concat([sampled_df] + synthetic_rows).reset_index(drop=True)
    else:
        full_df = sampled_df

    logger.info(
        "Final dataset prepared: %d transactions across exactly %d unique users.",
        len(full_df),
        full_df["synthetic_user_id"].nunique(),
    )
    return full_df


async def run():
    t_start = time.time()
    logger.info("============================================================")
    logger.info("SEEDING DIGITAL TWINS & TRANSACTIONS FOR ALL 2,000 USERS")
    logger.info("============================================================")

    if not CSV_PATH.exists():
        logger.error("creditcard.csv not found at %s", CSV_PATH)
        sys.exit(1)

    # 1. Load models
    logger.info("Loading model artifacts from %s...", MODELS_DIR)
    xgb_model = joblib.load(MODELS_DIR / "xgboost_model.joblib")
    xgb_booster = xgb_model.get_booster()
    if_artifact = joblib.load(MODELS_DIR / "isolation_forest_model.joblib")
    iso_forest = if_artifact["model"]
    if_score_min = float(if_artifact["score_min"])
    if_score_max = float(if_artifact["score_max"])
    scaler = joblib.load(MODELS_DIR / "scaler.joblib")

    with open(MODELS_DIR / "model_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    feature_names = meta.get("feature_names", [])

    # 2. Prepare data
    df_raw = pd.read_csv(CSV_PATH)
    full_df = build_sampled_dataset(df_raw)

    # 3. Compute behavioral features user-by-user
    logger.info("Computing behavioral features user-by-user (chronological)...")
    engine = BehavioralFeatureEngine()
    behavioral_records = []
    
    # Sort full_df by Time for causality
    full_df = full_df.sort_values("Time").reset_index(drop=True)

    for _, row in full_df.iterrows():
        uid = str(row["synthetic_user_id"])
        t_val = float(row["Time"])
        amt_val = float(row["Amount"])
        dev_marker = f"{uid}_{int(t_val // 3600)}"

        feats = engine.compute_and_update(
            user_id=uid,
            timestamp=t_val,
            amount=amt_val,
            device_marker=dev_marker,
        )
        behavioral_records.append(feats)

    beh_df = pd.DataFrame(behavioral_records, index=full_df.index)

    # 4. Scale Amount & Time
    scaled_vals = scaler.transform(full_df[["Amount", "Time"]])
    scaled_df = pd.DataFrame(scaled_vals, columns=["Amount", "Time"], index=full_df.index)

    # 5. Build feature matrix for ML scoring
    v_cols = [f"V{i}" for i in range(1, 29)]
    merged_features = pd.concat([full_df[v_cols], scaled_df, beh_df], axis=1)
    X_mat = merged_features[feature_names].values.astype(np.float32)

    logger.info("Scoring %d transactions with XGBoost...", len(X_mat))
    xgb_scores = xgb_model.predict_proba(X_mat)[:, 1]

    logger.info("Scoring %d transactions with Isolation Forest...", len(X_mat))
    if_raw_scores = iso_forest.decision_function(X_mat)
    if_scores = np.clip((if_raw_scores - if_score_min) / (if_score_max - if_score_min + 1e-9), 0.0, 1.0)

    # Fusion
    final_scores = 0.70 * xgb_scores + 0.30 * if_scores
    decision_tiers = [
        "BLOCK" if s >= 0.85 else "REVIEW" if s >= 0.50 else "APPROVE" for s in final_scores
    ]

    full_df["xgb_score"] = xgb_scores
    full_df["if_score"] = if_scores
    full_df["final_score"] = final_scores
    full_df["decision_tier"] = decision_tiers
    full_df["tx_uuid"] = [str(uuid.uuid4()) for _ in range(len(full_df))]

    # 6. Re-update DigitalTwinEngine profiles with risk scores & metadata
    logger.info("Finalizing Digital Twin profiles with risk scores & history...")
    for i, row in full_df.iterrows():
        uid = str(row["synthetic_user_id"])
        score = float(row["final_score"])
        engine.compute_and_update(
            user_id=uid,
            timestamp=float(row["Time"]),
            amount=float(row["Amount"]),
            risk_score=score,
            tx_metadata={
                "transaction_uuid": row["tx_uuid"],
                "amount": float(row["Amount"]),
                "final_score": round(score, 4),
                "decision_tier": row["decision_tier"],
                "timestamp": float(row["Time"]),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )

    # 7. Compute native SHAP for flagged rows (BLOCK / REVIEW) + sample APPROVE
    import xgboost as xgb
    flagged_mask = full_df["decision_tier"].isin(["BLOCK", "REVIEW"]) | (np.arange(len(full_df)) % 10 == 0)
    flagged_indices = np.where(flagged_mask)[0]
    logger.info("Computing native XGBoost SHAP values for %d priority transactions...", len(flagged_indices))

    dmat_flagged = xgb.DMatrix(X_mat[flagged_indices], feature_names=feature_names)
    shap_contribs = xgb_booster.predict(dmat_flagged, pred_contribs=True)

    shap_records_by_idx = {}
    for local_idx, global_idx in enumerate(flagged_indices):
        contrib = shap_contribs[local_idx, :-1]  # drop bias term
        row_features = X_mat[global_idx]
        top_k = np.argsort(np.abs(contrib))[::-1][:10]

        shap_list = []
        for rank, f_idx in enumerate(top_k, start=1):
            s_val = float(contrib[f_idx])
            f_name = feature_names[f_idx]
            f_val = float(row_features[f_idx])
            direction = "increases_risk" if s_val > 0 else "decreases_risk"
            shap_list.append({
                "feature_name": f_name,
                "shap_value": round(s_val, 6),
                "feature_value": round(f_val, 4),
                "direction": direction,
                "rank": rank,
            })
        shap_records_by_idx[global_idx] = shap_list

    # 8. Database Persistence
    logger.info("Connecting to PostgreSQL database at %s...", DB_URL)
    engine_db = create_async_engine(DB_URL, echo=False)

    async with engine_db.begin() as conn:
        logger.info("Cleaning previous transaction data while preserving auth users...")
        await conn.execute(text("DELETE FROM shap_explanations;"))
        await conn.execute(text("DELETE FROM review_queue;"))
        await conn.execute(text("DELETE FROM transactions;"))
        await conn.execute(text("DELETE FROM digital_twin_profiles;"))
        await conn.execute(text("DELETE FROM users;"))

        # 8a. Insert all 2,000 users
        logger.info("Inserting 2,000 users into users table...")
        all_unique_uids = sorted(full_df["synthetic_user_id"].unique())
        user_rows = [{"synthetic_user_id": uid} for uid in all_unique_uids]
        
        # Batch insert users
        await conn.execute(
            text("INSERT INTO users (synthetic_user_id, created_at) VALUES (:synthetic_user_id, NOW())"),
            user_rows
        )
        
        # Fetch user IDs mapping
        res = await conn.execute(text("SELECT id, synthetic_user_id FROM users;"))
        uid_to_id = {row[1]: row[0] for row in res.fetchall()}

        # 8b. Insert Digital Twin profiles
        logger.info("Inserting 2,000 profiles into digital_twin_profiles table...")
        dt_profile_rows = []
        for uid in all_unique_uids:
            prof_dict = engine.get_profile_dict(uid)
            dt_profile_rows.append({
                "user_id": uid_to_id[uid],
                "synthetic_user_id": uid,
                "rolling_stats": json.dumps(prof_dict) if prof_dict else json.dumps({}),
            })

        await conn.execute(
            text("""
                INSERT INTO digital_twin_profiles (user_id, synthetic_user_id, rolling_stats, updated_at)
                VALUES (:user_id, :synthetic_user_id, CAST(:rolling_stats AS json), NOW())
            """),
            dt_profile_rows
        )

        # 8c. Insert transactions
        logger.info("Inserting %d transactions...", len(full_df))
        tx_rows = []
        for i, row in full_df.iterrows():
            uid = str(row["synthetic_user_id"])
            v_dict = {f"V{j}": float(row[f"V{j}"]) for j in range(1, 29)}
            beh_row = beh_df.iloc[i]

            tx_rows.append({
                "transaction_uuid": row["tx_uuid"],
                "user_id": uid_to_id[uid],
                "synthetic_user_id": uid,
                "time_val": float(row["Time"]),
                "amount": float(row["Amount"]),
                "v_features": json.dumps(v_dict),
                "tx_freq_1h": float(beh_row["tx_freq_1h"]),
                "tx_freq_24h": float(beh_row["tx_freq_24h"]),
                "amount_deviation_z": float(beh_row["amount_deviation_z"]),
                "time_of_day_risk": int(beh_row["time_of_day_risk"]),
                "velocity_change": float(beh_row["velocity_change"]),
                "location_entropy": int(beh_row["location_entropy"]),
                "xgb_score": round(float(row["xgb_score"]), 6),
                "if_score": round(float(row["if_score"]), 6),
                "final_score": round(float(row["final_score"]), 6),
                "decision_tier": row["decision_tier"],
                "is_simulation": True,
                "true_label": int(row["Class"]),
            })

        # Insert transactions in chunks of 2,000 for high performance
        chunk_size = 2000
        for start_idx in range(0, len(tx_rows), chunk_size):
            chunk = tx_rows[start_idx : start_idx + chunk_size]
            await conn.execute(
                text("""
                    INSERT INTO transactions (
                        transaction_uuid, user_id, synthetic_user_id, time_val, amount,
                        v_features, tx_freq_1h, tx_freq_24h, amount_deviation_z,
                        time_of_day_risk, velocity_change, location_entropy,
                        xgb_score, if_score, final_score, decision_tier,
                        is_simulation, true_label, created_at
                    ) VALUES (
                        :transaction_uuid, :user_id, :synthetic_user_id, :time_val, :amount,
                        CAST(:v_features AS json), :tx_freq_1h, :tx_freq_24h, :amount_deviation_z,
                        :time_of_day_risk, :velocity_change, :location_entropy,
                        :xgb_score, :if_score, :final_score, :decision_tier,
                        :is_simulation, :true_label, NOW()
                    )
                """),
                chunk
            )

        # 8d. Fetch generated transaction IDs
        res_tx = await conn.execute(
            text("SELECT id, transaction_uuid, decision_tier FROM transactions;")
        )
        tx_lookup = {row[1]: (row[0], row[2]) for row in res_tx.fetchall()}

        # 8e. Insert SHAP explanations
        shap_db_rows = []
        for global_idx, explanations in shap_records_by_idx.items():
            tx_uuid = full_df.iloc[global_idx]["tx_uuid"]
            if tx_uuid in tx_lookup:
                tx_id, _ = tx_lookup[tx_uuid]
                for exp in explanations:
                    shap_db_rows.append({
                        "transaction_id": tx_id,
                        "feature_name": exp["feature_name"],
                        "shap_value": exp["shap_value"],
                        "feature_value": exp["feature_value"],
                        "direction": exp["direction"],
                        "rank": exp["rank"],
                    })

        if shap_db_rows:
            logger.info("Inserting %d SHAP feature contribution rows...", len(shap_db_rows))
            for start_idx in range(0, len(shap_db_rows), 3000):
                chunk = shap_db_rows[start_idx : start_idx + 3000]
                await conn.execute(
                    text("""
                        INSERT INTO shap_explanations (transaction_id, feature_name, shap_value, feature_value, direction, rank)
                        VALUES (:transaction_id, :feature_name, :shap_value, :feature_value, :direction, :rank)
                    """),
                    chunk
                )

        # 8f. Insert Review Queue items
        review_queue_rows = []
        for tx_uuid, (tx_id, tier) in tx_lookup.items():
            if tier == "REVIEW":
                review_queue_rows.append({
                    "transaction_id": tx_id,
                    "status": "pending",
                })

        if review_queue_rows:
            logger.info("Inserting %d pending review queue items...", len(review_queue_rows))
            await conn.execute(
                text("""
                    INSERT INTO review_queue (transaction_id, status, created_at)
                    VALUES (:transaction_id, :status, NOW())
                """),
                review_queue_rows
            )

    await engine_db.dispose()
    logger.info("============================================================")
    logger.info("SUCCESSFULLY SEEDED ALL 2,000 USERS & PROFILES in %.2fs!", time.time() - t_start)
    logger.info("  * Total Users:              %d", len(all_unique_uids))
    logger.info("  * Total Transactions:       %d", len(full_df))
    logger.info("  * Total Profiles:           %d", len(dt_profile_rows))
    logger.info("  * SHAP Explanations:        %d", len(shap_db_rows))
    logger.info("  * Review Queue Items:       %d", len(review_queue_rows))
    logger.info("  * user_0414 Status:         EXISTS (has transactions & profile)")
    logger.info("============================================================")


if __name__ == "__main__":
    asyncio.run(run())
