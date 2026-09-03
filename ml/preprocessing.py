"""
ml/preprocessing.py
====================
Data cleaning, preprocessing, and splitting for the ULB European Credit Card
Fraud Detection dataset (creditcard.csv).

Thesis Reference: Chapter 3, Section 3.2 — Data Preprocessing
Dataset: 284,807 transactions, 31 columns (Time, V1-V28, Amount, Class)
         Fraud: 492 rows (~0.17%)

SYNTHETIC USER IDs
------------------
The ULB dataset has no user_id, device_id, or geolocation fields — this is
a known limitation acknowledged in the thesis. To compute behavioral features
(Section 3.3 / Table 4), we synthesize a deterministic pseudo-user identity
using a hash-bucket approach:

  synthetic_user_id = hash( floor(Time / TIME_BUCKET_SECONDS) ,
                            floor(Amount / AMOUNT_BUCKET_SIZE) )
                      modulo SYNTHETIC_USER_POOL_SIZE

This maps transactions into a pool of SYNTHETIC_USER_POOL_SIZE (2000) user
buckets reproducibly (seed-independent — pure deterministic hash). Transactions
with similar time-of-day patterns AND similar spend levels are grouped together,
approximating a realistic user behavioral cluster.

This synthetic proxy is required solely for computing behavioral features during
offline training. At live inference the calling system is expected to pass a
real user_id; if it passes a synthetic one for demo purposes, the same formula
is applied. Every occurrence is clearly labeled in code and in the frontend
"About the Dataset" panel.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from imblearn.combine import SMOTEENN
from imblearn.pipeline import Pipeline as ImbPipeline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RANDOM_STATE: int = 42

# Synthetic user identity parameters (CLEARLY LABELED — see module docstring)
SYNTHETIC_USER_POOL_SIZE: int = 2_000  # pool of pseudo-user IDs for training
TIME_BUCKET_SECONDS: float = 3_600.0   # 1-hour buckets for time binning
AMOUNT_BUCKET_SIZE: float = 25.0       # $25 buckets for amount binning

# Feature columns present in the raw CSV
RAW_FEATURE_COLS = [f"V{i}" for i in range(1, 29)] + ["Amount", "Time"]
SCALED_COLS = ["Amount", "Time"]       # only these two need StandardScaler
PCA_COLS = [f"V{i}" for i in range(1, 29)]  # already PCA-normalized, leave as-is
TARGET_COL = "Class"


# ---------------------------------------------------------------------------
# Synthetic User ID Generation
# NOTE: This is a synthetic proxy required because the ULB dataset has no
# native user/device/geo fields. It is used ONLY for computing behavioral
# features during offline training and live demo replay. It is NOT used for
# any production fraud signal. Clearly labeled here, in the README, and in
# the frontend "About the Dataset" panel.
# ---------------------------------------------------------------------------

def generate_synthetic_user_id(time_val: float, amount_val: float) -> str:
    """
    Deterministically assign a synthetic user ID to a transaction based on
    its Time and Amount values.

    Algorithm:
      1. Bin Time into 1-hour buckets (floor(Time / 3600))
      2. Bin Amount into $25 buckets (floor(Amount / 25))
      3. Combine as string "T{time_bin}_A{amount_bin}"
      4. MD5-hash the string, take first 8 hex chars, convert to int
      5. Modulo SYNTHETIC_USER_POOL_SIZE to land in [0, 1999]
      6. Return as "user_{index:04d}"

    This is deterministic: same (time, amount) always produces the same ID.
    Seed-independent — no random state involved.
    """
    time_bin = int(time_val // TIME_BUCKET_SECONDS)
    amount_bin = int(max(amount_val, 0) // AMOUNT_BUCKET_SIZE)
    key = f"T{time_bin}_A{amount_bin}"
    hash_int = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
    user_index = hash_int % SYNTHETIC_USER_POOL_SIZE
    return f"user_{user_index:04d}"


def add_synthetic_user_ids(df: pd.DataFrame) -> pd.DataFrame:
    """
    Vectorized application of generate_synthetic_user_id across the DataFrame.
    Adds column 'synthetic_user_id' (str).
    """
    logger.info("Generating synthetic user IDs (SYNTHETIC PROXY — see module docstring)")
    df = df.copy()
    # Vectorised: bin then hash
    time_bins = (df["Time"] // TIME_BUCKET_SECONDS).astype(int)
    amount_bins = (df["Amount"].clip(lower=0) // AMOUNT_BUCKET_SIZE).astype(int)
    keys = "T" + time_bins.astype(str) + "_A" + amount_bins.astype(str)
    hash_ints = keys.apply(lambda k: int(hashlib.md5(k.encode()).hexdigest()[:8], 16))
    user_indices = (hash_ints % SYNTHETIC_USER_POOL_SIZE)
    df["synthetic_user_id"] = "user_" + user_indices.apply(lambda x: f"{x:04d}")
    unique_users = df["synthetic_user_id"].nunique()
    logger.info(
        "Synthetic user IDs assigned. Unique users in dataset: %d / %d pool",
        unique_users, SYNTHETIC_USER_POOL_SIZE,
    )
    return df


# ---------------------------------------------------------------------------
# Step 1: Load & Validate
# ---------------------------------------------------------------------------

def load_and_validate(csv_path: str | Path) -> Tuple[pd.DataFrame, dict]:
    """
    Load creditcard.csv and perform initial validation.

    Checks:
    - File exists and is readable
    - Expected columns are present
    - No unexpected nulls in V1-V28, Amount, Time, Class
    - Class column contains only {0, 1}

    Returns:
        df: Loaded DataFrame
        report: Dict with initial stats (rows, cols, null counts, class dist)
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {csv_path}. "
            "Place creditcard.csv at data/raw/creditcard.csv."
        )

    logger.info("Loading dataset from %s", csv_path)
    df = pd.read_csv(csv_path)
    logger.info("Loaded %d rows × %d columns", len(df), len(df.columns))

    # Check expected columns
    expected_cols = set(["Time", "Amount", "Class"] + [f"V{i}" for i in range(1, 29)])
    missing_cols = expected_cols - set(df.columns)
    extra_cols = set(df.columns) - expected_cols
    if missing_cols:
        raise ValueError(f"Missing expected columns: {missing_cols}")
    if extra_cols:
        logger.warning("Extra unexpected columns found (will be ignored): %s", extra_cols)
        df = df[list(expected_cols)]

    # Null check
    null_counts = df[list(expected_cols)].isnull().sum()
    total_nulls = null_counts.sum()
    if total_nulls > 0:
        logger.warning("Null values detected:\n%s", null_counts[null_counts > 0].to_string())
    else:
        logger.info("No null values found in any expected column — dataset is clean.")

    # Class distribution
    class_dist = df[TARGET_COL].value_counts().to_dict()
    fraud_count = class_dist.get(1, 0)
    legit_count = class_dist.get(0, 0)
    fraud_pct = 100 * fraud_count / len(df) if len(df) > 0 else 0
    logger.info(
        "Class distribution — Legitimate: %d (%.2f%%), Fraud: %d (%.4f%%)",
        legit_count, 100 - fraud_pct, fraud_count, fraud_pct,
    )

    # Unexpected class values
    unexpected_classes = df[~df[TARGET_COL].isin([0, 1])][TARGET_COL].unique()
    if len(unexpected_classes) > 0:
        logger.warning("Unexpected Class values: %s", unexpected_classes)

    report = {
        "rows_loaded": len(df),
        "columns": list(df.columns),
        "null_counts": null_counts.to_dict(),
        "total_nulls": int(total_nulls),
        "class_distribution": {str(k): int(v) for k, v in class_dist.items()},
        "fraud_percentage": round(fraud_pct, 6),
    }
    return df, report


# ---------------------------------------------------------------------------
# Step 2: Remove Duplicates
# ---------------------------------------------------------------------------

def remove_duplicates(df: pd.DataFrame, report: dict) -> Tuple[pd.DataFrame, dict]:
    """
    Detect and remove exact duplicate rows (all 31 columns identical).
    Logs the count removed.
    """
    initial_rows = len(df)
    df_deduped = df.drop_duplicates()
    removed = initial_rows - len(df_deduped)

    if removed > 0:
        logger.info("Removed %d exact duplicate rows (%.4f%% of dataset)", removed, 100 * removed / initial_rows)
    else:
        logger.info("No exact duplicate rows found.")

    report["duplicates_removed"] = removed
    report["rows_after_dedup"] = len(df_deduped)
    return df_deduped.reset_index(drop=True), report


# ---------------------------------------------------------------------------
# Step 3: Type & Range Sanity Checks
# ---------------------------------------------------------------------------

def sanity_checks(df: pd.DataFrame, report: dict) -> Tuple[pd.DataFrame, dict]:
    """
    Enforce domain constraints and log/remove violating rows:
    - Amount >= 0
    - Class in {0, 1}
    - Time within [0, max observed] (no negatives)
    - V1-V28 not infinitely large (abs < 1e10)
    """
    initial_rows = len(df)
    violations = pd.Series(False, index=df.index)

    # Amount >= 0
    amount_neg = df["Amount"] < 0
    n_amount_neg = amount_neg.sum()
    if n_amount_neg > 0:
        logger.warning("Removing %d rows with negative Amount values", n_amount_neg)
        violations |= amount_neg
    report["sanity_amount_negative"] = int(n_amount_neg)

    # Class in {0, 1}
    bad_class = ~df["Class"].isin([0, 1])
    n_bad_class = bad_class.sum()
    if n_bad_class > 0:
        logger.warning("Removing %d rows with invalid Class values (not 0 or 1)", n_bad_class)
        violations |= bad_class
    report["sanity_bad_class"] = int(n_bad_class)

    # Time >= 0
    time_neg = df["Time"] < 0
    n_time_neg = time_neg.sum()
    if n_time_neg > 0:
        logger.warning("Removing %d rows with negative Time values", n_time_neg)
        violations |= time_neg
    report["sanity_time_negative"] = int(n_time_neg)

    # V features: flag extreme outliers (abs > 1e10 suggests data corruption)
    pca_cols = [f"V{i}" for i in range(1, 29)]
    extreme_v = (df[pca_cols].abs() > 1e10).any(axis=1)
    n_extreme_v = extreme_v.sum()
    if n_extreme_v > 0:
        logger.warning("Removing %d rows with extreme PCA feature values (|V| > 1e10)", n_extreme_v)
        violations |= extreme_v
    report["sanity_extreme_pca"] = int(n_extreme_v)

    # Null rows (catch anything that slipped through)
    null_rows = df.isnull().any(axis=1)
    n_null = null_rows.sum()
    if n_null > 0:
        logger.warning("Dropping %d rows with remaining null values", n_null)
        violations |= null_rows
    report["sanity_null_rows_dropped"] = int(n_null)

    df_clean = df[~violations].reset_index(drop=True)
    total_removed = initial_rows - len(df_clean)
    logger.info("Sanity checks: removed %d rows total. Remaining: %d", total_removed, len(df_clean))
    report["sanity_total_removed"] = total_removed
    report["rows_after_sanity"] = len(df_clean)
    return df_clean, report


# ---------------------------------------------------------------------------
# Step 4: Stratified Split (80/20 + 15% validation from train)
# ---------------------------------------------------------------------------

def stratified_split(
    df: pd.DataFrame,
    report: dict,
    test_size: float = 0.20,
    val_fraction_of_train: float = 0.15,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """
    Stratified split into train / val / test.

    Split strategy:
      - 80% train, 20% test (stratified on Class)
      - From the 80% train, carve out 15% as validation (also stratified)
      - Result: ~68% train, ~12% val, ~20% test of total dataset

    Asserts class ratios are preserved (±0.05% of raw fraud rate) in each split.
    """
    y = df[TARGET_COL]
    X = df.drop(columns=[TARGET_COL])

    # Train+val / Test split
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=RANDOM_STATE
    )

    # Train / Val split
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval,
        test_size=val_fraction_of_train,
        stratify=y_trainval,
        random_state=RANDOM_STATE,
    )

    # Verify class ratios
    raw_fraud_rate = y.mean()
    for name, y_split in [("train", y_train), ("val", y_val), ("test", y_test)]:
        split_rate = y_split.mean()
        tolerance = 0.0005  # allow ±0.05% absolute deviation
        assert abs(split_rate - raw_fraud_rate) < tolerance, (
            f"Class ratio violated in {name} split: {split_rate:.6f} vs {raw_fraud_rate:.6f} "
            f"(tolerance ±{tolerance})"
        )
        logger.info(
            "Split '%s': %d rows, fraud=%.6f%% (%.4f%% in raw)",
            name, len(y_split), 100 * split_rate, 100 * raw_fraud_rate,
        )

    report["split"] = {
        "train_rows": len(y_train),
        "val_rows": len(y_val),
        "test_rows": len(y_test),
        "train_fraud_pct": round(100 * y_train.mean(), 6),
        "val_fraud_pct": round(100 * y_val.mean(), 6),
        "test_fraud_pct": round(100 * y_test.mean(), 6),
        "raw_fraud_pct": round(100 * raw_fraud_rate, 6),
    }

    # Reassemble full DataFrames with labels
    train_df = X_train.copy(); train_df[TARGET_COL] = y_train
    val_df = X_val.copy();   val_df[TARGET_COL] = y_val
    test_df = X_test.copy(); test_df[TARGET_COL] = y_test

    return train_df, val_df, test_df, report


# ---------------------------------------------------------------------------
# Step 5: Feature Scaling (Amount + Time only; V1-V28 already PCA-normalized)
# ---------------------------------------------------------------------------

def fit_and_apply_scaler(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    scaler_path: str | Path,
    report: dict,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, StandardScaler, dict]:
    """
    Fit StandardScaler on the training split only (Amount + Time).
    Transform train, val, and test with the fitted scaler.
    V1-V28 are left unchanged (already PCA-normalized by dataset providers).
    Persist the fitted scaler to scaler_path using joblib.
    """
    scaler_path = Path(scaler_path)
    scaler_path.parent.mkdir(parents=True, exist_ok=True)

    scaler = StandardScaler()
    # Fit ONLY on training data to prevent data leakage
    scaler.fit(train_df[SCALED_COLS])
    logger.info("Fitted StandardScaler on training split for columns: %s", SCALED_COLS)
    logger.info("Scaler means: %s", dict(zip(SCALED_COLS, scaler.mean_)))
    logger.info("Scaler stds:  %s", dict(zip(SCALED_COLS, scaler.scale_)))

    # Transform all splits
    for name, df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        df[SCALED_COLS] = scaler.transform(df[SCALED_COLS])
        logger.info("Applied scaler transform to '%s' split", name)

    # Persist scaler
    joblib.dump(scaler, scaler_path)
    logger.info("Scaler persisted to %s", scaler_path)

    report["scaler"] = {
        "fitted_on": "train_split_only",
        "columns_scaled": SCALED_COLS,
        "columns_unchanged": PCA_COLS,
        "path": str(scaler_path),
        "mean_Amount": float(scaler.mean_[0]),
        "std_Amount": float(scaler.scale_[0]),
        "mean_Time": float(scaler.mean_[1]),
        "std_Time": float(scaler.scale_[1]),
    }
    return train_df, val_df, test_df, scaler, report


# ---------------------------------------------------------------------------
# Step 6: SMOTE-ENN Pipeline Builder (for use inside CV folds)
# ---------------------------------------------------------------------------

def build_smoteenn_pipeline(estimator) -> ImbPipeline:
    """
    Build an imbalanced-learn Pipeline that applies SMOTE-ENN internally
    within each cross-validation fold — NEVER globally before splitting.

    This prevents data leakage: the resampled synthetic minority class examples
    are created only from the training fold's data, never contaminating val/test.

    Thesis Reference: Section 3.5 — Class Imbalance Handling

    Args:
        estimator: A scikit-learn compatible estimator (e.g., XGBClassifier)

    Returns:
        ImbPipeline with steps: [('smoteenn', SMOTEENN), ('clf', estimator)]
    """
    smoteenn = SMOTEENN(
        random_state=RANDOM_STATE,
        # SMOTE ratio: oversample minority to 10% of majority (not 1:1 to keep realism)
        # ENN then cleans noisy examples from both classes
        smote_kwargs={
            "k_neighbors": 5,
            "random_state": RANDOM_STATE,
        },
    )
    pipeline = ImbPipeline(steps=[
        ("smoteenn", smoteenn),
        ("clf", estimator),
    ])
    return pipeline


# ---------------------------------------------------------------------------
# Step 7: Save Processed Data to Parquet
# ---------------------------------------------------------------------------

def save_processed_data(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    output_dir: str | Path,
    report: dict,
) -> None:
    """
    Save cleaned/processed splits to data/processed/ as Parquet files
    (columnar, fast read, preserves dtypes exactly).
    Also writes preprocessing_report.json.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    splits = {"train": train_df, "val": val_df, "test": test_df}
    for name, df in splits.items():
        path = output_dir / f"{name}.parquet"
        df.to_parquet(path, index=False, engine="pyarrow")
        logger.info("Saved %s split: %s (%d rows)", name, path, len(df))
        report[f"{name}_parquet_path"] = str(path)

    report_path = output_dir / "preprocessing_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Preprocessing report written to %s", report_path)


# ---------------------------------------------------------------------------
# Step 8: Load Processed Data (for use by training and verification)
# ---------------------------------------------------------------------------

def load_processed_data(processed_dir: str | Path) -> dict:
    """
    Load the parquet splits from data/processed/.
    Returns dict with keys: train_df, val_df, test_df (with Class column).
    """
    processed_dir = Path(processed_dir)
    result = {}
    for name in ("train", "val", "test"):
        path = processed_dir / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"Processed split '{name}.parquet' not found at {path}. "
                "Run scripts/run_preprocessing.py first."
            )
        df = pd.read_parquet(path, engine="pyarrow")
        result[f"{name}_df"] = df
        logger.info("Loaded '%s' split: %d rows", name, len(df))
    return result


def load_scaler(scaler_path: str | Path) -> StandardScaler:
    """Load the fitted StandardScaler from disk."""
    path = Path(scaler_path)
    if not path.exists():
        raise FileNotFoundError(f"Scaler not found at {path}. Run preprocessing first.")
    return joblib.load(path)


# ---------------------------------------------------------------------------
# Main Pipeline Entry Point
# ---------------------------------------------------------------------------

def run_preprocessing_pipeline(
    csv_path: str | Path,
    processed_dir: str | Path,
    scaler_path: str | Path,
) -> dict:
    """
    Run the full preprocessing pipeline end-to-end:
    1. Load & validate
    2. Remove duplicates
    3. Sanity checks
    4. Add synthetic user IDs (SYNTHETIC PROXY — see module docstring)
    5. Stratified split (80/20 + 15% val)
    6. Fit & apply StandardScaler (Amount + Time only)
    7. Save to parquet + preprocessing_report.json

    Args:
        csv_path: Path to creditcard.csv
        processed_dir: Output directory for parquet files + report
        scaler_path: Path to save the fitted scaler (joblib)

    Returns:
        report: Dict with all preprocessing statistics
    """
    report: dict = {"pipeline_version": "1.0.0"}

    # Steps 1–3: Load, deduplicate, sanity check
    df, report = load_and_validate(csv_path, )
    report["rows_initial"] = report["rows_loaded"]

    df, report = remove_duplicates(df, report)
    df, report = sanity_checks(df, report)

    # Step 4: Synthetic user IDs (SYNTHETIC PROXY)
    df = add_synthetic_user_ids(df)
    report["synthetic_user_pool_size"] = SYNTHETIC_USER_POOL_SIZE
    report["synthetic_user_note"] = (
        "SYNTHETIC PROXY: user IDs are hash-bucketed from Time+Amount bins. "
        "Required because the ULB dataset has no native user/device/geo fields. "
        "Used only for behavioral feature computation during training/demo."
    )

    # Step 5: Stratified split
    train_df, val_df, test_df, report = stratified_split(df, report)

    # Step 6: Fit scaler on training data only, then transform all splits
    train_df, val_df, test_df, scaler, report = fit_and_apply_scaler(
        train_df, val_df, test_df, scaler_path, report
    )

    # Step 7: Save parquet + report
    save_processed_data(train_df, val_df, test_df, processed_dir, report)

    logger.info("=" * 60)
    logger.info("PREPROCESSING COMPLETE")
    logger.info("  Initial rows:       %d", report["rows_initial"])
    logger.info("  Duplicates removed: %d", report["duplicates_removed"])
    logger.info("  Sanity removed:     %d", report["sanity_total_removed"])
    logger.info("  Train rows:         %d (fraud: %.4f%%)", report["split"]["train_rows"], report["split"]["train_fraud_pct"])
    logger.info("  Val rows:           %d (fraud: %.4f%%)", report["split"]["val_rows"],   report["split"]["val_fraud_pct"])
    logger.info("  Test rows:          %d (fraud: %.4f%%)", report["split"]["test_rows"],  report["split"]["test_fraud_pct"])
    logger.info("=" * 60)

    return report
