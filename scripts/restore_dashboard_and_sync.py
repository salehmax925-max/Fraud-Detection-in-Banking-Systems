"""
scripts/restore_dashboard_and_sync.py
======================================
Restores the Live Dashboard to its intended ~700 scored simulation transactions
with realistic decision tier distributions (approx 176 Auto-Blocked, 18-30 Under Review,
500 Auto-Approved), while PRESERVING all 2,000 Digital Twin profiles in
digital_twin_profiles table (including user_0414).
"""
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(BACKEND_DIR))

from app.services.scoring import initialize_scoring_service
from ml.features import BehavioralFeatureEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("restore_dashboard")

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://fraud:fraud_pass@localhost:5432/frauddb"
).replace("localhost", "127.0.0.1")


async def run():
    logger.info("Initializing ScoringService with official models...")
    scoring_svc = initialize_scoring_service(ROOT_DIR / "models")

    # 1. Load test split
    test_parquet = ROOT_DIR / "data" / "processed" / "test.parquet"
    logger.info("Loading test data from %s...", test_parquet)
    test_df = pd.read_parquet(test_parquet)

    fraud_df = test_df[test_df["Class"] == 1]
    legit_df = test_df[test_df["Class"] == 0]

    # Sample exactly 700 rows with 35% fraud (demo mode)
    n_fraud = int(700 * 0.35)  # 245 fraud rows
    n_legit = 700 - n_fraud     # 455 legit rows

    s_fraud = fraud_df.sample(n=n_fraud, random_state=42, replace=True)
    s_legit = legit_df.sample(n=n_legit, random_state=42)
    sample_700 = pd.concat([s_fraud, s_legit]).sample(frac=1, random_state=42).reset_index(drop=True)

    # Ensure user_0414 is present in the dashboard transactions as well
    if "user_0414" not in sample_700["synthetic_user_id"].values:
        u414_row = legit_df[legit_df["synthetic_user_id"] == "user_0414"]
        if len(u414_row) > 0:
            sample_700.iloc[0] = u414_row.iloc[0]

    logger.info("Scoring 700 transactions through the official ScoringService...")
    engine_beh = BehavioralFeatureEngine()
    scored_records = []

    for i, row in sample_700.iterrows():
        uid = str(row["synthetic_user_id"])
        t_val = float(row["Time"])
        amt_val = float(row["Amount"])
        v_features = [float(row[f"V{j}"]) for j in range(1, 29)]

        beh_feats = engine_beh.compute_and_update(
            user_id=uid,
            timestamp=t_val,
            amount=amt_val,
            device_marker=f"{uid}_{int(t_val // 3600)}",
        )

        score_res = scoring_svc.score_transaction(
            v_features=v_features,
            amount=amt_val,
            time_val=t_val,
            behavioral_features=beh_feats,
        )

        scored_records.append({
            "synthetic_user_id": uid,
            "time_val": t_val,
            "amount": amt_val,
            "v_features": {f"V{j}": v_features[j - 1] for j in range(1, 29)},
            "tx_freq_1h": beh_feats.get("tx_freq_1h", 0.0),
            "tx_freq_24h": beh_feats.get("tx_freq_24h", 0.0),
            "amount_deviation_z": beh_feats.get("amount_deviation_z", 0.0),
            "time_of_day_risk": beh_feats.get("time_of_day_risk", 0),
            "velocity_change": beh_feats.get("velocity_change", 0.0),
            "location_entropy": beh_feats.get("location_entropy", 0),
            "xgb_score": score_res["xgb_score"],
            "if_score": score_res["if_score"],
            "final_score": score_res["final_score"],
            "decision_tier": score_res["decision_tier"],
            "true_label": int(row["Class"]),
            "feature_vector": score_res["feature_vector"],
        })

    df_scored = pd.DataFrame(scored_records)
    tier_counts = df_scored["decision_tier"].value_counts()
    logger.info("Scoring complete! Decision tier breakdown:")
    for tier, cnt in tier_counts.items():
        logger.info("  * %s: %d", tier, cnt)

    # Database updates
    logger.info("Connecting to PostgreSQL at %s...", DB_URL)
    engine_db = create_async_engine(DB_URL, echo=False)

    async with engine_db.begin() as conn:
        # Fetch user ID mapping
        res = await conn.execute(text("SELECT id, synthetic_user_id FROM users;"))
        uid_to_id = {row[1]: row[0] for row in res.fetchall()}

        # Clear old dashboard transactions, explanations, and review queue
        logger.info("Clearing bloated transactions and review queue...")
        await conn.execute(text("DELETE FROM shap_explanations;"))
        await conn.execute(text("DELETE FROM review_queue;"))
        await conn.execute(text("DELETE FROM transactions;"))

        # Insert 700 transactions
        logger.info("Inserting 700 properly scored transactions...")
        tx_insert_rows = []
        shap_tasks = []

        for idx, r in df_scored.iterrows():
            tx_uuid = str(uuid.uuid4())
            uid = r["synthetic_user_id"]
            user_db_id = uid_to_id.get(uid)

            if user_db_id is None:
                # User not yet in users table, insert on the fly
                res_u = await conn.execute(
                    text("INSERT INTO users (synthetic_user_id, created_at) VALUES (:u, NOW()) RETURNING id;"),
                    {"u": uid}
                )
                user_db_id = res_u.scalar()
                uid_to_id[uid] = user_db_id

            tx_insert_rows.append({
                "transaction_uuid": tx_uuid,
                "user_id": user_db_id,
                "synthetic_user_id": uid,
                "time_val": r["time_val"],
                "amount": r["amount"],
                "v_features": json.dumps(r["v_features"]),
                "tx_freq_1h": r["tx_freq_1h"],
                "tx_freq_24h": r["tx_freq_24h"],
                "amount_deviation_z": r["amount_deviation_z"],
                "time_of_day_risk": r["time_of_day_risk"],
                "velocity_change": r["velocity_change"],
                "location_entropy": r["location_entropy"],
                "xgb_score": r["xgb_score"],
                "if_score": r["if_score"],
                "final_score": r["final_score"],
                "decision_tier": r["decision_tier"],
                "is_simulation": True,
                "true_label": r["true_label"],
            })

            # Prepare SHAP for flagged rows or top priority
            if r["decision_tier"] in ("BLOCK", "REVIEW") or idx % 5 == 0:
                shap_tasks.append((tx_uuid, r["feature_vector"]))

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
            tx_insert_rows
        )

        # Get generated transaction IDs
        res_tx = await conn.execute(text("SELECT id, transaction_uuid, decision_tier FROM transactions;"))
        tx_lookup = {row[1]: (row[0], row[2]) for row in res_tx.fetchall()}

        # Insert SHAP explanations
        logger.info("Computing SHAP explanations for %d priority transactions...", len(shap_tasks))
        shap_db_rows = []
        for tx_uuid, feat_vec in shap_tasks:
            if tx_uuid in tx_lookup:
                tx_id, _ = tx_lookup[tx_uuid]
                explanations = scoring_svc.get_shap_explanation(np.array(feat_vec), top_n=10)
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
            logger.info("Inserting %d SHAP explanations...", len(shap_db_rows))
            await conn.execute(
                text("""
                    INSERT INTO shap_explanations (transaction_id, feature_name, shap_value, feature_value, direction, rank)
                    VALUES (:transaction_id, :feature_name, :shap_value, :feature_value, :direction, :rank)
                """),
                shap_db_rows
            )

        # Insert Review Queue items
        review_items = [
            {"transaction_id": tid, "status": "pending"}
            for _, (tid, tier) in tx_lookup.items() if tier == "REVIEW"
        ]
        if review_items:
            logger.info("Inserting %d review queue items...", len(review_items))
            await conn.execute(
                text("""
                    INSERT INTO review_queue (transaction_id, status, created_at)
                    VALUES (:transaction_id, :status, NOW())
                """),
                review_items
            )

        # Verify stats
        cnt_total = await conn.execute(text("SELECT count(*) FROM transactions;"))
        cnt_block = await conn.execute(text("SELECT count(*) FROM transactions WHERE decision_tier = 'BLOCK';"))
        cnt_rev = await conn.execute(text("SELECT count(*) FROM transactions WHERE decision_tier = 'REVIEW';"))
        cnt_app = await conn.execute(text("SELECT count(*) FROM transactions WHERE decision_tier = 'APPROVE';"))
        cnt_pend = await conn.execute(text("SELECT count(*) FROM review_queue WHERE status = 'pending';"))
        cnt_profiles = await conn.execute(text("SELECT count(*) FROM digital_twin_profiles;"))

        logger.info("============================================================")
        logger.info("DASHBOARD RESTORED TO REALISTIC DEMO SIMULATION STATS:")
        logger.info("  * Total Scored:       %d", cnt_total.scalar())
        logger.info("  * Auto-Blocked:       %d", cnt_block.scalar())
        logger.info("  * Under Review:       %d", cnt_rev.scalar())
        logger.info("  * Auto-Approved:      %d", cnt_app.scalar())
        logger.info("  * Pending Reviews:    %d", cnt_pend.scalar())
        logger.info("  * Digital Twins:      %d profiles maintained in DB", cnt_profiles.scalar())
        logger.info("============================================================")

    await engine_db.dispose()


if __name__ == "__main__":
    asyncio.run(run())
