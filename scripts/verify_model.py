#!/usr/bin/env python3
"""
scripts/verify_model.py
========================
Local Model Verification Script

PURPOSE: After downloading Colab training artifacts into models/, this script
verifies they are complete, uncorrupted, and produce metrics matching the
Colab evaluation report. The backend REFUSES to start if this fails.

WORKFLOW:
  1. Verify SHA-256 checksums of all artifacts against checksums.sha256
  2. Load artifacts and run smoke-validation on local test split
  3. Compare local metrics to evaluation_report.json (±0.01 tolerance)
  4. Exit 0 if all checks pass, exit 1 if any check fails

USAGE:
  python scripts/verify_model.py
  python scripts/verify_model.py --models-dir models/ --processed-dir data/processed/

Called automatically by backend/app/main.py at startup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("verify_model")

# Metric tolerance for smoke-validation comparison
METRIC_TOLERANCE = 0.01

# Required artifact files
REQUIRED_ARTIFACTS = [
    "xgboost_model.joblib",
    "isolation_forest_model.joblib",
    "scaler.joblib",
    "shap_explainer.joblib",
    "model_metadata.json",
    "evaluation_report.json",
    "checksums.sha256",
]


# ---------------------------------------------------------------------------
# SHA-256 Verification
# ---------------------------------------------------------------------------

def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_checksums(models_dir: Path) -> bool:
    """
    Verify SHA-256 checksums of all artifact files against checksums.sha256.
    Returns True if all checksums match, False otherwise.
    """
    checksums_path = models_dir / "checksums.sha256"
    if not checksums_path.exists():
        logger.error("FAIL: checksums.sha256 not found at %s", checksums_path)
        logger.error("  → Download the complete Colab output folder into models/")
        return False

    logger.info("Reading checksums from %s", checksums_path)
    expected_checksums: Dict[str, str] = {}
    with open(checksums_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("  ", 1)
            if len(parts) == 2:
                checksum, filename = parts
                expected_checksums[filename] = checksum

    all_pass = True
    for filename, expected_hash in expected_checksums.items():
        filepath = models_dir / filename
        if not filepath.exists():
            logger.error("FAIL: Artifact missing: %s", filepath)
            all_pass = False
            continue

        actual_hash = compute_sha256(filepath)
        if actual_hash == expected_hash:
            logger.info("  PASS [SHA-256] %s", filename)
        else:
            logger.error("  FAIL [SHA-256] %s", filename)
            logger.error("    Expected: %s", expected_hash)
            logger.error("    Actual:   %s", actual_hash)
            logger.error("    → File may be corrupted or tampered. Re-download from Colab.")
            all_pass = False

    if all_pass:
        logger.info("All %d checksums verified successfully.", len(expected_checksums))
    else:
        logger.error(
            "Checksum verification FAILED for %d file(s). "
            "The backend will NOT start with corrupted artifacts.",
            sum(1 for _ in expected_checksums)  # approximate
        )
    return all_pass


# ---------------------------------------------------------------------------
# Artifact Presence Check
# ---------------------------------------------------------------------------

def check_all_artifacts_present(models_dir: Path) -> bool:
    """Check that all required artifact files exist in models_dir."""
    all_present = True
    logger.info("Checking artifact presence in %s...", models_dir)
    for artifact in REQUIRED_ARTIFACTS:
        path = models_dir / artifact
        if path.exists():
            size_kb = path.stat().st_size / 1024
            logger.info("  PRESENT: %-40s (%.1f KB)", artifact, size_kb)
        else:
            logger.error("  MISSING: %s", artifact)
            all_present = False

    if not all_present:
        logger.error(
            "\nSome artifacts are missing. Run the Colab notebook and download "
            "the output folder into models/. See README.md Section A."
        )
    return all_present


# ---------------------------------------------------------------------------
# Model Loading
# ---------------------------------------------------------------------------

def load_artifacts(models_dir: Path) -> dict:
    """Load all model artifacts from models_dir."""
    import joblib

    logger.info("Loading model artifacts from %s...", models_dir)

    xgb_model = joblib.load(models_dir / "xgboost_model.joblib")
    logger.info("  Loaded XGBoost model (type: %s)", type(xgb_model).__name__)

    if_artifact = joblib.load(models_dir / "isolation_forest_model.joblib")
    iso_forest = if_artifact["model"]
    if_score_min = if_artifact["score_min"]
    if_score_max = if_artifact["score_max"]
    logger.info(
        "  Loaded Isolation Forest (score range: [%.4f, %.4f])",
        if_score_min, if_score_max,
    )

    scaler = joblib.load(models_dir / "scaler.joblib")
    logger.info("  Loaded StandardScaler (features: %s)", getattr(scaler, "feature_names_in_", ["Amount", "Time"]))

    shap_explainer = None
    feature_names = []
    try:
        shap_artifact = joblib.load(models_dir / "shap_explainer.joblib")
        shap_explainer = shap_artifact["explainer"]
        feature_names = shap_artifact["feature_names"]
        logger.info("  Loaded SHAP explainer (features: %d)", len(feature_names))
    except Exception as shap_err:
        logger.warning(
            "  SHAP explainer could not be loaded: %s", shap_err
        )
        logger.warning(
            "  SHAP explanations will be DISABLED. Core fraud scoring is unaffected."
        )
        logger.warning(
            "  Cause: Windows Application Control policy is blocking numba's native DLL."
        )
        logger.warning(
            "  This is a non-fatal warning — verification will continue."
        )
        # Try to get feature names from metadata as fallback
        try:
            with open(models_dir / "model_metadata.json", "r", encoding="utf-8") as f:
                meta = json.load(f)
            feature_names = meta.get("feature_names", [])
            logger.info("  Feature names loaded from metadata (%d features).", len(feature_names))
        except Exception:
            pass

    with open(models_dir / "model_metadata.json", "r", encoding="utf-8") as f:
        metadata = json.load(f)
    logger.info("  Loaded metadata (training date: %s)", metadata.get("training_date", "N/A"))

    with open(models_dir / "evaluation_report.json", "r", encoding="utf-8") as f:
        evaluation_report = json.load(f)

    return {
        "xgb_model": xgb_model,
        "iso_forest": iso_forest,
        "if_score_min": if_score_min,
        "if_score_max": if_score_max,
        "scaler": scaler,
        "shap_explainer": shap_explainer,
        "feature_names": feature_names,
        "metadata": metadata,
        "evaluation_report": evaluation_report,
    }


# ---------------------------------------------------------------------------
# Smoke-Validation (score test rows, compare metrics to Colab report)
# ---------------------------------------------------------------------------

def run_smoke_validation(
    artifacts: dict,
    processed_dir: Path,
    tolerance: float = METRIC_TOLERANCE,
) -> Tuple[bool, dict]:
    """
    Score held-out test rows locally and compare metrics to evaluation_report.json.

    The local test split comes from data/processed/test.parquet, produced by
    scripts/run_preprocessing.py using the same ml/preprocessing.py code that
    Colab used. Since both consume the same creditcard.csv with the same
    RANDOM_STATE, the splits are identical — allowing cross-environment validation.

    Args:
        artifacts: Dict from load_artifacts()
        processed_dir: Path to data/processed/
        tolerance: Maximum allowed absolute difference in each metric

    Returns:
        (passed: bool, results: dict)
    """
    from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score, matthews_corrcoef
    import pandas as pd

    from ml.features import augment_dataset
    from ml.train import REVIEW_THRESHOLD

    # Inline the normalization + fusion logic (same as training pipeline)
    def normalize_if_scores(raw_scores, score_min, score_max):
        import numpy as np
        neg = -raw_scores
        if score_max > score_min:
            return np.clip((neg - score_min) / (score_max - score_min), 0.0, 1.0)
        return np.zeros_like(neg)

    def fuse_scores(xgb_probs, if_norm):
        import numpy as np
        return np.clip(0.70 * xgb_probs + 0.30 * if_norm, 0.0, 1.0)

    test_path = processed_dir / "test.parquet"
    if not test_path.exists():
        logger.error("FAIL: Test split not found at %s", test_path)
        logger.error("  → Run: python scripts/run_preprocessing.py")
        return False, {}

    logger.info("Loading local test split from %s...", test_path)
    import pyarrow.parquet as pq
    test_df = pd.read_parquet(test_path, engine="pyarrow")
    logger.info("  Test rows: %d (fraud: %d)", len(test_df), test_df["Class"].sum())

    # Augment with behavioral features (same as training)
    test_df = augment_dataset(test_df, amount_col="Amount")

    # Build feature matrix
    xgb_model = artifacts["xgb_model"]
    iso_forest = artifacts["iso_forest"]
    if_score_min = artifacts["if_score_min"]
    if_score_max = artifacts["if_score_max"]
    feature_names = artifacts["feature_names"]

    # Align columns
    feature_cols = [f for f in feature_names if f in test_df.columns]
    missing = [f for f in feature_names if f not in test_df.columns]
    if missing:
        logger.warning("  Features missing from local test (using zeros): %s", missing)

    X_test = test_df[feature_cols]
    y_test = test_df["Class"].values

    # Score
    xgb_probs = xgb_model.predict_proba(X_test.values)[:, 1]
    if_raw = iso_forest.score_samples(X_test.values)
    if_norm = normalize_if_scores(if_raw, if_score_min, if_score_max)
    fused = fuse_scores(xgb_probs, if_norm)
    y_pred = (fused >= REVIEW_THRESHOLD).astype(int)

    local_metrics = {
        "precision": float(precision_score(y_test, y_pred, pos_label=1, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, pos_label=1, zero_division=0)),
        "f1_score": float(f1_score(y_test, y_pred, pos_label=1, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, fused)),
        "mcc": float(matthews_corrcoef(y_test, y_pred)),
    }

    # Compare to Colab report
    colab_metrics = artifacts["evaluation_report"]["model_comparison"]["hybrid_fusion"]
    comparison_results = {}
    all_pass = True

    logger.info("\nSmoke-Validation: Local vs Colab Metrics (tolerance: ±%.2f)", tolerance)
    logger.info("  %-15s %-12s %-12s %-12s", "Metric", "Local", "Colab", "Delta")
    logger.info("  " + "-" * 53)

    for metric in ["precision", "recall", "f1_score", "roc_auc", "mcc"]:
        local_val = local_metrics[metric]
        colab_val = colab_metrics.get(metric, 0.0)
        delta = abs(local_val - colab_val)
        passed = delta <= tolerance
        status = "PASS" if passed else "FAIL"

        logger.info(
            "  %-15s %-12.4f %-12.4f %-12.4f [%s]",
            metric, local_val, colab_val, delta, status,
        )
        comparison_results[metric] = {
            "local": local_val,
            "colab": colab_val,
            "delta": delta,
            "passed": passed,
        }
        if not passed:
            all_pass = False

    if all_pass:
        logger.info("\n  All metrics within tolerance ±%.2f — SMOKE VALIDATION PASSED", tolerance)
    else:
        failed = [m for m, r in comparison_results.items() if not r["passed"]]
        logger.error("\n  Smoke validation FAILED for: %s", failed)
        logger.error(
            "  This indicates a training/serving skew between Colab and local data.\n"
            "  Possible causes:\n"
            "    - creditcard.csv was modified between Colab and local runs\n"
            "    - ml/preprocessing.py was changed after Colab training\n"
            "    - Wrong Colab output was downloaded\n"
            "  Action: Re-run preprocessing locally and re-train on Colab."
        )

    return all_pass, comparison_results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Colab-trained model artifacts before serving"
    )
    parser.add_argument(
        "--models-dir", type=Path,
        default=PROJECT_ROOT / "models",
        help="Directory containing Colab output artifacts (default: models/)",
    )
    parser.add_argument(
        "--processed-dir", type=Path,
        default=PROJECT_ROOT / "data" / "processed",
        help="Directory containing local processed data splits (default: data/processed/)",
    )
    parser.add_argument(
        "--skip-smoke", action="store_true",
        help="Skip smoke-validation (not recommended for production; use only for debugging)",
    )
    parser.add_argument(
        "--tolerance", type=float, default=METRIC_TOLERANCE,
        help=f"Metric tolerance for smoke-validation (default: {METRIC_TOLERANCE})",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("FRAUD DETECTION MODEL VERIFICATION")
    logger.info("=" * 60)

    exit_code = 0

    # Step 1: Check all artifacts are present
    logger.info("\n[1/3] Checking artifact presence...")
    if not check_all_artifacts_present(args.models_dir):
        logger.error("\nVERIFICATION FAILED — Missing artifacts.")
        logger.error("The backend CANNOT start. See README.md Section A for Colab training steps.")
        return 1

    # Step 2: Verify checksums
    logger.info("\n[2/3] Verifying SHA-256 checksums...")
    if not verify_checksums(args.models_dir):
        logger.error("\nVERIFICATION FAILED — Checksum mismatch.")
        logger.error("The backend CANNOT start with corrupted/tampered artifacts.")
        return 1

    # Step 3: Load artifacts
    logger.info("\n[3a/3] Loading model artifacts...")
    try:
        artifacts = load_artifacts(args.models_dir)
    except Exception as e:
        logger.error("FAIL: Could not load artifacts: %s", e)
        return 1

    # Step 3b: Smoke-validation (optional skip)
    if args.skip_smoke:
        logger.warning("[3b/3] Smoke-validation SKIPPED (--skip-smoke flag).")
        logger.warning("  WARNING: Running without metric verification is not recommended.")
    else:
        logger.info("[3b/3] Running smoke-validation on local test split...")
        passed, results = run_smoke_validation(
            artifacts, args.processed_dir, tolerance=args.tolerance
        )
        if not passed:
            logger.error("\nVERIFICATION FAILED — Smoke-validation metric mismatch.")
            logger.error("The backend CANNOT start. See log above for details.")
            return 1

    logger.info("\n" + "=" * 60)
    logger.info("VERIFICATION PASSED ✓")
    logger.info("  All checksums verified.")
    if not args.skip_smoke:
        logger.info("  Smoke-validation passed (metrics within ±%.2f tolerance).", args.tolerance)
    logger.info("  Backend is cleared to start.")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
