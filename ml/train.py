"""
ml/train.py
============
Hybrid Fraud Detection Model — XGBoost + Isolation Forest + Optuna Tuning

Thesis Reference: Chapter 3, Section 3.4–3.8 — Model Design
                  Table 6 — Optuna Hyperparameter Search Space
                  Section 3.7 — Score Fusion (0.70 XGB + 0.30 IF)
                  Section 3.8 — Tiered Decision Thresholds

Architecture:
  1. Primary Classifier  — XGBoost (supervised, handles class imbalance with scale_pos_weight)
     Tuned via Optuna Bayesian TPE search (100 trials, 5-fold stratified CV)
     SMOTE-ENN applied INSIDE each CV fold via imbalanced-learn Pipeline
  2. Secondary Anomaly   — Isolation Forest (unsupervised, no labels used)
     Scores normalized to [0, 1] range
  3. Score Fusion        — final_score = 0.70 * xgb_prob + 0.30 * if_score_normalized
  4. Tiered Decisions    — final_score > 0.85 → auto-block
                           0.50 ≤ final_score ≤ 0.85 → analyst review
                           final_score < 0.50 → auto-approve
  5. Explainability      — SHAP TreeExplainer on XGBoost for all score ≥ 0.50

Artifacts produced (saved to models/ directory):
  - xgboost_model.joblib
  - isolation_forest_model.joblib
  - scaler.joblib              (copied from data/processed/)
  - shap_explainer.joblib
  - model_metadata.json
  - checksums.sha256
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import joblib
import numpy as np
import optuna
import pandas as pd
# shap is imported lazily inside compute_shap_explainer() and get_shap_top_features()
# to avoid crashing on machines where numba's DLL is blocked by Windows App Control.
from imblearn.combine import SMOTEENN
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    matthews_corrcoef,
    confusion_matrix,
)
from sklearn.model_selection import StratifiedKFold
from xgboost import XGBClassifier

from ml.features import (
    BehavioralFeatureEngine,
    BEHAVIORAL_FEATURE_COLS,
    augment_dataset,
    get_feature_names_for_model,
)
from ml.preprocessing import (
    RANDOM_STATE,
    load_processed_data,
    build_smoteenn_pipeline,
)

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Fusion weights and thresholds (thesis-defended values — do not change)
# ---------------------------------------------------------------------------
XGB_WEIGHT: float = 0.70
IF_WEIGHT: float = 0.30

BLOCK_THRESHOLD: float = 0.85
REVIEW_THRESHOLD: float = 0.50
# final_score > 0.85 → BLOCK
# 0.50 ≤ final_score ≤ 0.85 → REVIEW
# final_score < 0.50 → APPROVE


# ---------------------------------------------------------------------------
# Feature column names (must match augment_dataset output order)
# ---------------------------------------------------------------------------

def get_X_y(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Extract feature matrix X and target vector y from a split DataFrame.
    Column order: V1-V28 (PCA, unchanged) + Amount + Time (scaled) + 5 behavioral.
    """
    feature_cols = get_feature_names_for_model()
    # Filter to only columns that exist in the df
    available = [c for c in feature_cols if c in df.columns]
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        logger.warning("Expected feature columns missing from DataFrame: %s", missing)
    X = df[available]
    y = df["Class"]
    return X, y


# ---------------------------------------------------------------------------
# Optuna Objective (SMOTE-ENN inside CV fold via Pipeline)
# ---------------------------------------------------------------------------

def _create_xgb_classifier(trial: optuna.Trial, scale_pos_weight: float) -> XGBClassifier:
    """
    Create an XGBClassifier with hyperparameters sampled from the Optuna trial.
    Search space matches Table 6 of the thesis exactly.
    """
    return XGBClassifier(
        # Table 6 hyperparameter search space
        learning_rate=trial.suggest_float("learning_rate", 0.005, 0.3, log=True),
        max_depth=trial.suggest_int("max_depth", 3, 10),
        n_estimators=trial.suggest_int("n_estimators", 100, 1000),
        subsample=trial.suggest_float("subsample", 0.5, 1.0),
        colsample_bytree=trial.suggest_float("colsample_bytree", 0.5, 1.0),
        reg_alpha=trial.suggest_float("reg_alpha", 0.0, 10.0),
        reg_lambda=trial.suggest_float("reg_lambda", 0.0, 10.0),
        # Fixed parameters
        scale_pos_weight=scale_pos_weight,
        use_label_encoder=False,
        eval_metric="logloss",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        tree_method="hist",  # fast CPU histogram method
    )


class OptunaObjective:
    """
    Optuna objective function for XGBoost hyperparameter optimization.

    Optimizes: F1-score on the minority class (fraud, Class=1)
    Strategy:  5-fold stratified cross-validation
    Resampling: SMOTE-ENN applied INSIDE each fold via ImbPipeline
               (never before splitting — prevents data leakage)
    """

    def __init__(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        n_folds: int = 5,
        scale_pos_weight: Optional[float] = None,
    ) -> None:
        self.X_train = X_train
        self.y_train = y_train
        self.n_folds = n_folds
        if scale_pos_weight is None:
            neg = (y_train == 0).sum()
            pos = (y_train == 1).sum()
            self.scale_pos_weight = float(neg / pos) if pos > 0 else 1.0
        else:
            self.scale_pos_weight = scale_pos_weight
        logger.info(
            "OptunaObjective initialized. Train rows: %d, fraud: %d (%.4f%%), "
            "scale_pos_weight: %.2f, CV folds: %d",
            len(y_train), y_train.sum(), 100 * y_train.mean(),
            self.scale_pos_weight, n_folds,
        )

    def __call__(self, trial: optuna.Trial) -> float:
        """
        Run one Optuna trial: build pipeline, cross-validate, return mean F1.
        SMOTE-ENN runs INSIDE each CV fold (via ImbPipeline).
        """
        xgb = _create_xgb_classifier(trial, self.scale_pos_weight)

        # imbalanced-learn Pipeline: resampling is step 1, classifier is step 2
        # When used inside StratifiedKFold.split(), SMOTE-ENN sees only
        # the fold's training data — no leakage to the fold's validation data.
        smoteenn = SMOTEENN(
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )
        pipeline = ImbPipeline(steps=[
            ("smoteenn", smoteenn),
            ("clf", xgb),
        ])

        cv = StratifiedKFold(n_splits=self.n_folds, shuffle=True, random_state=RANDOM_STATE)
        fold_f1_scores = []

        X_arr = self.X_train.values
        y_arr = self.y_train.values

        for fold_idx, (train_idx, val_idx) in enumerate(cv.split(X_arr, y_arr)):
            X_fold_train = X_arr[train_idx]
            y_fold_train = y_arr[train_idx]
            X_fold_val = X_arr[val_idx]
            y_fold_val = y_arr[val_idx]

            # Pipeline.fit() applies SMOTE-ENN only to (X_fold_train, y_fold_train)
            pipeline.fit(X_fold_train, y_fold_train)

            # Predict on the UNRESAMPELD validation fold
            y_pred = pipeline.predict(X_fold_val)
            f1 = f1_score(y_fold_val, y_pred, pos_label=1, zero_division=0)
            fold_f1_scores.append(f1)

            trial.report(np.mean(fold_f1_scores), fold_idx)
            if trial.should_prune():
                raise optuna.exceptions.TrialPruned()

        mean_f1 = float(np.mean(fold_f1_scores))
        return mean_f1


# ---------------------------------------------------------------------------
# Optuna Search
# ---------------------------------------------------------------------------

def run_optuna_search(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    n_trials: int = 100,
    n_folds: int = 5,
    study_name: str = "fraud_xgb_tuning",
    show_progress: bool = True,
) -> Tuple[Dict[str, Any], float]:
    """
    Run Bayesian hyperparameter search using Optuna TPE sampler.

    Args:
        X_train: Training features
        y_train: Training labels
        n_trials: Number of Optuna trials (thesis: 100; adjust for Colab runtime)
        n_folds: CV folds (thesis: 5)
        study_name: Optuna study name for logging
        show_progress: Whether to show Optuna progress bar

    Returns:
        best_params: Dict of best hyperparameters
        best_value: Best mean CV F1-score achieved
    """
    logger.info("=" * 60)
    logger.info("Starting Optuna Bayesian hyperparameter search")
    logger.info("  Trials: %d, CV folds: %d", n_trials, n_folds)
    logger.info("  Objective: F1-score (minority class = fraud)")
    logger.info("  Sampler: Tree-structured Parzen Estimator (TPE)")
    logger.info("=" * 60)

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    study = optuna.create_study(
        direction="maximize",
        study_name=study_name,
        sampler=optuna.samplers.TPESampler(seed=RANDOM_STATE),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10, n_warmup_steps=2),
    )

    objective = OptunaObjective(X_train, y_train, n_folds=n_folds)

    start_time = time.time()
    study.optimize(
        objective,
        n_trials=n_trials,
        show_progress_bar=show_progress,
        n_jobs=1,  # sequential for reproducibility
    )
    elapsed = time.time() - start_time

    best_params = study.best_params
    best_value = study.best_value

    logger.info("=" * 60)
    logger.info("Optuna search complete in %.1f minutes", elapsed / 60)
    logger.info("Best CV F1 (fraud class): %.4f", best_value)
    logger.info("Best parameters:")
    for k, v in best_params.items():
        logger.info("  %s: %s", k, v)
    logger.info("=" * 60)

    return best_params, best_value


# ---------------------------------------------------------------------------
# Train Final XGBoost (on full train set with best params)
# ---------------------------------------------------------------------------

def train_xgboost_final(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    best_params: Dict[str, Any],
    X_val: Optional[pd.DataFrame] = None,
    y_val: Optional[pd.Series] = None,
) -> XGBClassifier:
    """
    Train the final XGBoost model on the full training set using best Optuna params.
    SMOTE-ENN is applied to the full training set once (not CV fold-wise,
    since we're now doing final training, not evaluation).
    """
    neg = (y_train == 0).sum()
    pos = (y_train == 1).sum()
    scale_pos_weight = float(neg / pos) if pos > 0 else 1.0

    logger.info("Training final XGBoost model with best parameters...")
    logger.info("  Training samples: %d (fraud: %d = %.4f%%)", len(y_train), pos, 100 * pos / len(y_train))
    logger.info("  scale_pos_weight: %.2f", scale_pos_weight)

    # Apply SMOTE-ENN to full training set for final model
    logger.info("Applying SMOTE-ENN to training data for final model...")
    smoteenn = SMOTEENN(random_state=RANDOM_STATE, n_jobs=-1)
    X_resampled, y_resampled = smoteenn.fit_resample(X_train.values, y_train.values)
    logger.info(
        "After SMOTE-ENN: %d rows (fraud: %d = %.2f%%)",
        len(y_resampled), y_resampled.sum(), 100 * y_resampled.mean(),
    )

    xgb = XGBClassifier(
        **best_params,
        scale_pos_weight=scale_pos_weight,
        use_label_encoder=False,
        eval_metric="logloss",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        tree_method="hist",
    )

    eval_set = None
    if X_val is not None and y_val is not None:
        eval_set = [(X_val.values, y_val.values)]

    xgb.fit(
        X_resampled,
        y_resampled,
        eval_set=eval_set,
        verbose=False,
    )

    logger.info("XGBoost training complete.")
    return xgb


# ---------------------------------------------------------------------------
# Train Isolation Forest
# ---------------------------------------------------------------------------

def train_isolation_forest(
    X_train: pd.DataFrame,
    contamination: float = 0.001,
) -> Tuple[IsolationForest, float, float]:
    """
    Train Isolation Forest on the full feature set, unsupervised (no labels).
    Computes the min/max of anomaly scores for normalization to [0, 1].

    Args:
        X_train: Training features
        contamination: Expected proportion of anomalies (≈ fraud rate)

    Returns:
        iso_forest: Trained IsolationForest
        score_min: Minimum raw anomaly score (for normalization)
        score_max: Maximum raw anomaly score (for normalization)
    """
    logger.info("Training Isolation Forest (unsupervised, contamination=%.4f)...", contamination)

    iso_forest = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        max_features=1.0,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        bootstrap=False,
    )
    iso_forest.fit(X_train.values)

    # Compute anomaly scores on training data to establish normalization bounds
    # score_samples() returns higher values for more normal observations,
    # so we negate: higher negated score = more anomalous
    raw_scores = iso_forest.score_samples(X_train.values)
    # Negate so higher = more anomalous (consistent with XGBoost probability direction)
    neg_scores = -raw_scores

    score_min = float(neg_scores.min())
    score_max = float(neg_scores.max())
    logger.info(
        "Isolation Forest trained. Raw score range: [%.4f, %.4f] (before negation)",
        raw_scores.min(), raw_scores.max(),
    )
    logger.info(
        "Negated score range for normalization: [%.4f, %.4f]",
        score_min, score_max,
    )
    return iso_forest, score_min, score_max


def normalize_if_scores(
    raw_scores: np.ndarray,
    score_min: float,
    score_max: float,
) -> np.ndarray:
    """
    Normalize Isolation Forest anomaly scores to [0, 1].
    Higher normalized score = more anomalous = higher fraud probability.

    raw_scores: output of iso_forest.score_samples() (higher = more normal)
    """
    neg_scores = -raw_scores  # negate: now higher = more anomalous
    if score_max > score_min:
        normalized = (neg_scores - score_min) / (score_max - score_min)
    else:
        normalized = np.zeros_like(neg_scores)
    return np.clip(normalized, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Score Fusion
# ---------------------------------------------------------------------------

def fuse_scores(
    xgb_probs: np.ndarray,
    if_normalized: np.ndarray,
    xgb_weight: float = XGB_WEIGHT,
    if_weight: float = IF_WEIGHT,
) -> np.ndarray:
    """
    Fuse XGBoost probability and Isolation Forest normalized score.

    Formula (thesis-defended):
        final_score = 0.70 * xgb_probability + 0.30 * if_score_normalized

    Args:
        xgb_probs:     XGBoost P(Class=1) probabilities [0, 1]
        if_normalized: Normalized IF anomaly scores [0, 1]
        xgb_weight:    Weight for XGBoost (default: 0.70)
        if_weight:     Weight for Isolation Forest (default: 0.30)

    Returns:
        fused_scores: Array of final scores [0, 1]
    """
    assert abs(xgb_weight + if_weight - 1.0) < 1e-6, "Weights must sum to 1.0"
    fused = xgb_weight * xgb_probs + if_weight * if_normalized
    return np.clip(fused, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Tiered Decision Thresholds
# ---------------------------------------------------------------------------

TIER_BLOCK = "BLOCK"
TIER_REVIEW = "REVIEW"
TIER_APPROVE = "APPROVE"


def apply_tiered_decision(
    final_scores: np.ndarray,
    block_threshold: float = BLOCK_THRESHOLD,
    review_threshold: float = REVIEW_THRESHOLD,
) -> List[str]:
    """
    Apply tiered decision logic to final fused scores.

    Thresholds (thesis-defended):
        final_score > 0.85 → BLOCK   (auto-block)
        0.50 ≤ final_score ≤ 0.85 → REVIEW  (analyst review)
        final_score < 0.50 → APPROVE (auto-approve)

    Args:
        final_scores: Array of fused scores [0, 1]
        block_threshold: Upper threshold (default 0.85)
        review_threshold: Lower threshold (default 0.50)

    Returns:
        List of decision tier strings ('BLOCK', 'REVIEW', 'APPROVE')
    """
    decisions = []
    for score in final_scores:
        if score > block_threshold:
            decisions.append(TIER_BLOCK)
        elif score >= review_threshold:
            decisions.append(TIER_REVIEW)
        else:
            decisions.append(TIER_APPROVE)
    return decisions


def score_single_transaction(
    xgb_model: XGBClassifier,
    iso_forest: IsolationForest,
    if_score_min: float,
    if_score_max: float,
    features: np.ndarray,
    block_threshold: float = BLOCK_THRESHOLD,
    review_threshold: float = REVIEW_THRESHOLD,
) -> dict:
    """
    Score a single transaction through the full fusion pipeline.

    Args:
        xgb_model: Trained XGBClassifier
        iso_forest: Trained IsolationForest
        if_score_min/max: Normalization bounds from training
        features: 1D or 2D numpy array of features
        block_threshold: BLOCK tier cutoff
        review_threshold: REVIEW tier cutoff

    Returns:
        dict with: xgb_score, if_score_raw, if_score_normalized,
                   final_score, decision_tier
    """
    if features.ndim == 1:
        features = features.reshape(1, -1)

    xgb_prob = float(xgb_model.predict_proba(features)[0, 1])
    if_raw = float(iso_forest.score_samples(features)[0])
    if_norm = float(normalize_if_scores(np.array([if_raw]), if_score_min, if_score_max)[0])
    final_score = float(fuse_scores(np.array([xgb_prob]), np.array([if_norm]))[0])
    tier = apply_tiered_decision(np.array([final_score]), block_threshold, review_threshold)[0]

    return {
        "xgb_score": round(xgb_prob, 6),
        "if_score_raw": round(if_raw, 6),
        "if_score_normalized": round(if_norm, 6),
        "final_score": round(final_score, 6),
        "decision_tier": tier,
    }


# ---------------------------------------------------------------------------
# SHAP Explainability
# ---------------------------------------------------------------------------

def compute_shap_explainer(
    xgb_model: XGBClassifier,
    X_background: pd.DataFrame,
    max_background_samples: int = 500,
) -> shap.TreeExplainer:
    """
    Build a SHAP TreeExplainer for the trained XGBoost model.

    Uses a random sample of training data as the background dataset
    (for efficiency — full training set is too large for interactive SHAP).

    Args:
        xgb_model: Trained XGBClassifier
        X_background: Training features (for background distribution)
        max_background_samples: Max rows to use as background

    Returns:
        shap.TreeExplainer instance
    """
    import shap  # lazy import — avoids numba DLL crash on Windows App Control machines
    logger.info("Building SHAP TreeExplainer...")
    if len(X_background) > max_background_samples:
        bg_sample = X_background.sample(
            n=max_background_samples, random_state=RANDOM_STATE
        )
    else:
        bg_sample = X_background

    explainer = shap.TreeExplainer(
        xgb_model,
        data=bg_sample.values,
        feature_perturbation="interventional",
        model_output="probability",
    )
    logger.info("SHAP TreeExplainer built with %d background samples.", len(bg_sample))
    return explainer


def get_shap_top_features(
    explainer: shap.TreeExplainer,
    features: np.ndarray,
    feature_names: List[str],
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    """
    Compute SHAP values for a single transaction and return top contributing
    features with their direction and magnitude.

    Args:
        explainer: Fitted SHAP TreeExplainer
        features: 1D or 2D numpy array of feature values
        feature_names: List of feature names (same order as features)
        top_n: Number of top features to return

    Returns:
        List of dicts: [{feature_name, shap_value, feature_value, direction, rank}]
        Sorted by |shap_value| descending.
    """
    import shap  # lazy import — avoids numba DLL crash on Windows App Control machines  # noqa: F401
    if features.ndim == 1:
        features = features.reshape(1, -1)

    shap_values = explainer.shap_values(features)
    # For binary classification, shap_values may be a list [class0, class1] or array
    if isinstance(shap_values, list):
        sv = shap_values[1][0]  # Class=1 (fraud) SHAP values
    else:
        sv = shap_values[0]

    # Pair feature names with SHAP values and actual feature values
    feature_vals = features[0]
    contributions = [
        {
            "feature_name": name,
            "shap_value": float(sv[i]),
            "feature_value": float(feature_vals[i]),
            "direction": "increases_risk" if sv[i] > 0 else "decreases_risk",
            "rank": 0,  # filled below
        }
        for i, name in enumerate(feature_names)
    ]

    # Sort by absolute SHAP value
    contributions.sort(key=lambda x: abs(x["shap_value"]), reverse=True)
    for rank, item in enumerate(contributions[:top_n], start=1):
        item["rank"] = rank

    return contributions[:top_n]


# ---------------------------------------------------------------------------
# Artifact Persistence + SHA-256 Checksums
# ---------------------------------------------------------------------------

def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def save_model_artifacts(
    xgb_model: XGBClassifier,
    iso_forest: IsolationForest,
    if_score_min: float,
    if_score_max: float,
    shap_explainer: shap.TreeExplainer,
    feature_names: List[str],
    best_params: Dict[str, Any],
    best_cv_f1: float,
    evaluation_metrics: Dict[str, Any],
    scaler_source_path: Path,
    output_dir: Path,
) -> Dict[str, str]:
    """
    Save all model artifacts to output_dir and compute SHA-256 checksums.

    Saved files:
        xgboost_model.joblib
        isolation_forest_model.joblib
        scaler.joblib               (copied from preprocessing output)
        shap_explainer.joblib
        model_metadata.json         (params, metrics, training info)
        checksums.sha256            (SHA-256 of every artifact above)

    Returns:
        dict mapping artifact names to their paths
    """
    import shutil
    from datetime import datetime, timezone

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    # 1. XGBoost model
    xgb_path = output_dir / "xgboost_model.joblib"
    joblib.dump(xgb_model, xgb_path)
    paths["xgboost_model.joblib"] = str(xgb_path)
    logger.info("Saved XGBoost model to %s", xgb_path)

    # 2. Isolation Forest model (include normalization bounds)
    if_artifact = {
        "model": iso_forest,
        "score_min": if_score_min,
        "score_max": if_score_max,
    }
    if_path = output_dir / "isolation_forest_model.joblib"
    joblib.dump(if_artifact, if_path)
    paths["isolation_forest_model.joblib"] = str(if_path)
    logger.info("Saved Isolation Forest model to %s", if_path)

    # 3. Scaler (copy from preprocessing output)
    scaler_dest = output_dir / "scaler.joblib"
    if Path(scaler_source_path).exists():
        shutil.copy2(scaler_source_path, scaler_dest)
        paths["scaler.joblib"] = str(scaler_dest)
        logger.info("Copied scaler to %s", scaler_dest)
    else:
        logger.warning("Scaler source not found at %s — skipping copy", scaler_source_path)

    # 4. SHAP explainer
    shap_path = output_dir / "shap_explainer.joblib"
    joblib.dump({
        "explainer": shap_explainer,
        "feature_names": feature_names,
    }, shap_path)
    paths["shap_explainer.joblib"] = str(shap_path)
    logger.info("Saved SHAP explainer to %s", shap_path)

    # 5. Model metadata
    import platform
    metadata = {
        "training_date": datetime.now(timezone.utc).isoformat(),
        "model_version": "1.0.0",
        "thesis_title": "Fraud Detection in Banking — Al-Balqa' Applied University",
        "training_environment": "Google Colab",
        "python_version": platform.python_version(),
        "optuna_best_params": best_params,
        "optuna_best_cv_f1": best_cv_f1,
        "fusion_weights": {"xgb": XGB_WEIGHT, "isolation_forest": IF_WEIGHT},
        "thresholds": {
            "block": BLOCK_THRESHOLD,
            "review": REVIEW_THRESHOLD,
        },
        "isolation_forest_normalization": {
            "score_min": if_score_min,
            "score_max": if_score_max,
        },
        "feature_names": feature_names,
        "feature_count": len(feature_names),
        "evaluation_metrics": evaluation_metrics,
    }
    meta_path = output_dir / "model_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str)
    paths["model_metadata.json"] = str(meta_path)
    logger.info("Saved model metadata to %s", meta_path)

    # 6. Compute SHA-256 checksums for all artifacts
    artifact_files = [
        "xgboost_model.joblib",
        "isolation_forest_model.joblib",
        "scaler.joblib",
        "shap_explainer.joblib",
        "model_metadata.json",
    ]
    checksums = {}
    for filename in artifact_files:
        fpath = output_dir / filename
        if fpath.exists():
            checksums[filename] = compute_sha256(fpath)
            logger.info("SHA-256 [%s]: %s", filename, checksums[filename])
        else:
            logger.warning("Artifact not found for checksum: %s", filename)

    checksums_path = output_dir / "checksums.sha256"
    with open(checksums_path, "w", encoding="utf-8") as f:
        for filename, checksum in checksums.items():
            f.write(f"{checksum}  {filename}\n")
    paths["checksums.sha256"] = str(checksums_path)
    logger.info("Checksums written to %s", checksums_path)

    return paths


# ---------------------------------------------------------------------------
# Full Training Pipeline Entry Point
# ---------------------------------------------------------------------------

def run_training_pipeline(
    processed_dir: str | Path,
    scaler_path: str | Path,
    output_dir: str | Path,
    n_optuna_trials: int = 100,
    n_cv_folds: int = 5,
) -> Dict[str, Any]:
    """
    Run the complete model training pipeline:
    1. Load processed data
    2. Augment with behavioral features
    3. Run Optuna search (n_trials, n_folds CV)
    4. Train final XGBoost
    5. Train Isolation Forest
    6. Build SHAP explainer
    7. Evaluate on test set
    8. Save artifacts + checksums

    Args:
        processed_dir: Path to data/processed/ with parquet splits
        scaler_path: Path to fitted scaler (data/processed/scaler.joblib)
        output_dir: Path to save model artifacts (models/)
        n_optuna_trials: Number of Optuna trials
        n_cv_folds: Number of CV folds

    Returns:
        results dict with model objects and evaluation metrics
    """
    from ml.evaluate import compute_all_metrics, save_evaluation_report

    logger.info("=" * 70)
    logger.info("FRAUD DETECTION TRAINING PIPELINE")
    logger.info("  Optuna trials: %d, CV folds: %d", n_optuna_trials, n_cv_folds)
    logger.info("=" * 70)

    # --- Load processed splits ---
    splits = load_processed_data(processed_dir)
    train_df = splits["train_df"]
    val_df = splits["val_df"]
    test_df = splits["test_df"]

    # --- Augment with behavioral features ---
    logger.info("Augmenting training split with behavioral features...")
    # NOTE: Training data in parquet has scaled Amount/Time. We augment
    # AFTER scaling since the behavioral engine uses relative values (z-score)
    # which are scale-invariant. The engine is initialized fresh per split
    # to avoid leakage between splits.
    train_df = augment_dataset(train_df, amount_col="Amount")
    val_df = augment_dataset(val_df, amount_col="Amount")
    test_df = augment_dataset(test_df, amount_col="Amount")

    # Save augmented splits for reference
    aug_dir = Path(processed_dir) / "augmented"
    aug_dir.mkdir(exist_ok=True)
    train_df.to_parquet(aug_dir / "train_augmented.parquet", index=False)
    val_df.to_parquet(aug_dir / "val_augmented.parquet", index=False)
    test_df.to_parquet(aug_dir / "test_augmented.parquet", index=False)
    logger.info("Augmented splits saved to %s", aug_dir)

    # --- Extract feature matrices ---
    X_train, y_train = get_X_y(train_df)
    X_val, y_val = get_X_y(val_df)
    X_test, y_test = get_X_y(test_df)
    feature_names = list(X_train.columns)
    logger.info("Feature count: %d", len(feature_names))

    # --- Optuna hyperparameter search ---
    best_params, best_cv_f1 = run_optuna_search(
        X_train, y_train,
        n_trials=n_optuna_trials,
        n_folds=n_cv_folds,
    )

    # --- Train final XGBoost ---
    xgb_model = train_xgboost_final(
        X_train, y_train,
        best_params=best_params,
        X_val=X_val, y_val=y_val,
    )

    # --- Validate on val set ---
    val_probs = xgb_model.predict_proba(X_val.values)[:, 1]
    val_preds = (val_probs > 0.5).astype(int)
    val_f1 = f1_score(y_val, val_preds, pos_label=1, zero_division=0)
    logger.info("Validation XGB-only F1 (threshold=0.5): %.4f", val_f1)

    # --- Train Isolation Forest ---
    iso_forest, if_score_min, if_score_max = train_isolation_forest(
        X_train, contamination=float(y_train.mean())
    )

    # --- Evaluate all three configurations on test set ---
    test_xgb_probs = xgb_model.predict_proba(X_test.values)[:, 1]
    test_if_raw = iso_forest.score_samples(X_test.values)
    test_if_norm = normalize_if_scores(test_if_raw, if_score_min, if_score_max)
    test_fused = fuse_scores(test_xgb_probs, test_if_norm)

    evaluation_metrics = compute_all_metrics(
        y_test=y_test.values,
        xgb_probs=test_xgb_probs,
        if_normalized=test_if_norm,
        fused_scores=test_fused,
        block_threshold=BLOCK_THRESHOLD,
        review_threshold=REVIEW_THRESHOLD,
        output_dir=Path(output_dir) / "plots",
        feature_names=feature_names,
        xgb_model=xgb_model,
        X_test=X_test,
    )

    # --- Build SHAP Explainer ---
    shap_explainer = compute_shap_explainer(xgb_model, X_train)

    # --- Save evaluation report ---
    save_evaluation_report(evaluation_metrics, Path(output_dir) / "evaluation_report.json")

    # --- Save all artifacts + checksums ---
    artifact_paths = save_model_artifacts(
        xgb_model=xgb_model,
        iso_forest=iso_forest,
        if_score_min=if_score_min,
        if_score_max=if_score_max,
        shap_explainer=shap_explainer,
        feature_names=feature_names,
        best_params=best_params,
        best_cv_f1=best_cv_f1,
        evaluation_metrics=evaluation_metrics,
        scaler_source_path=Path(scaler_path),
        output_dir=Path(output_dir),
    )

    logger.info("=" * 70)
    logger.info("TRAINING PIPELINE COMPLETE")
    logger.info("  Artifact paths: %s", artifact_paths)
    logger.info("=" * 70)

    return {
        "xgb_model": xgb_model,
        "iso_forest": iso_forest,
        "if_score_min": if_score_min,
        "if_score_max": if_score_max,
        "shap_explainer": shap_explainer,
        "feature_names": feature_names,
        "best_params": best_params,
        "best_cv_f1": best_cv_f1,
        "evaluation_metrics": evaluation_metrics,
        "artifact_paths": artifact_paths,
    }
