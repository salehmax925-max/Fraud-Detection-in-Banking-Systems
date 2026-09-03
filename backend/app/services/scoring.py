"""
backend/app/services/scoring.py
================================
Fraud Scoring Service — loads model artifacts and performs live inference.

This is the inference twin of ml/train.py. It loads the exact same artifacts
produced by Colab training and executes the same scoring pipeline:
  Raw features → StandardScaler → XGBoost + IF → Fusion → Tiered Decision → SHAP

Thread Safety:
  Model artifacts are loaded once at startup (singleton pattern).
  Scoring is stateless per request (models only predict, never mutate).
  DigitalTwinEngine handles per-user stateful updates with asyncio locks.

Startup Gate:
  This service REFUSES to initialize if model verification fails.
  (Called from main.py lifespan startup hook)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Add project root so ml/ is importable
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


class ScoringService:
    """
    Singleton service that loads model artifacts once and provides:
      - score_transaction(): full pipeline for one transaction
      - get_shap_top_features(): SHAP explanation for a scored transaction
    """

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self._loaded = False

        # Model artifacts (populated by load())
        self.xgb_model = None
        self._xgb_booster = None      # raw Booster for native SHAP pred_contribs
        self.iso_forest = None
        self.if_score_min: float = 0.0
        self.if_score_max: float = 1.0
        self.scaler = None
        self.shap_explainer = None    # kept for interface compatibility; not used
        self.feature_names: List[str] = []
        self.metadata: Dict[str, Any] = {}
        self.evaluation_report: Dict[str, Any] = {}

        # Live-adjustable thresholds (loaded from DB on each request via endpoint)
        self._block_threshold: float = 0.85
        self._review_threshold: float = 0.50

    def load(self) -> None:
        """
        Load all model artifacts from models_dir.
        Called once at backend startup AFTER verification passes.

        SHAP Strategy:
            We do NOT load shap_explainer.joblib — it is incompatible on Windows due to:
              1. numba bytecode mismatch (Python 3.10 vs Colab Python 3.12 — "code expected
                 at most 16 arguments, got 18")
              2. SHAP 0.49 bug: XGBoost 2.0+ stores base_score as '[0.88]' (bracketed string)
                 which shap.TreeExplainer cannot parse.
            Instead, we cache the raw XGBoost Booster and use xgboost's own
            pred_contribs=True SHAP implementation — confirmed working locally.
        """
        import joblib, json

        logger.info("Loading model artifacts from %s...", self.models_dir)

        self.xgb_model = joblib.load(self.models_dir / "xgboost_model.joblib")
        # Cache the raw booster for native SHAP (avoids shap library entirely)
        try:
            self._xgb_booster = self.xgb_model.get_booster()
            logger.info("  XGBoost model loaded (type: %s), booster cached for native SHAP", type(self.xgb_model).__name__)
        except Exception as e:
            self._xgb_booster = None
            logger.warning("  Could not cache XGB booster: %s", e)

        if_artifact = joblib.load(self.models_dir / "isolation_forest_model.joblib")
        self.iso_forest = if_artifact["model"]
        self.if_score_min = float(if_artifact["score_min"])
        self.if_score_max = float(if_artifact["score_max"])
        logger.info("  Isolation Forest loaded (score range: [%.4f, %.4f])", self.if_score_min, self.if_score_max)

        self.scaler = joblib.load(self.models_dir / "scaler.joblib")
        logger.info("  StandardScaler loaded")

        # Load feature names from metadata (used for SHAP labeling)
        with open(self.models_dir / "model_metadata.json", "r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        self.feature_names = self.metadata.get("feature_names", [])
        logger.info(
            "  Feature names loaded from metadata (%d features). "
            "SHAP will use native XGBoost pred_contribs (shap_explainer.joblib skipped).",
            len(self.feature_names),
        )

        with open(self.models_dir / "evaluation_report.json", "r", encoding="utf-8") as f:
            self.evaluation_report = json.load(f)

        self._loaded = True
        logger.info("All model artifacts loaded successfully.")

    def update_thresholds(self, block_threshold: float, review_threshold: float) -> None:
        """Update live thresholds (called when admin updates via API)."""
        self._block_threshold = block_threshold
        self._review_threshold = review_threshold
        logger.info(
            "Thresholds updated: block=%.2f, review=%.2f",
            block_threshold, review_threshold,
        )

    def _build_feature_vector(
        self,
        v_features: List[float],
        amount_scaled: float,
        time_scaled: float,
        behavioral_features: dict,
    ) -> np.ndarray:
        """
        Build the feature vector in the EXACT same order as during training.
        Order: V1-V28 + Amount_scaled + Time_scaled + 6 behavioral features
        """
        from ml.features import BEHAVIORAL_FEATURE_COLS
        behavioral_vals = [behavioral_features.get(col, 0.0) for col in BEHAVIORAL_FEATURE_COLS]
        feature_vec = v_features + [amount_scaled, time_scaled] + behavioral_vals
        return np.array(feature_vec, dtype=np.float64).reshape(1, -1)

    def score_transaction(
        self,
        v_features: List[float],
        amount: float,
        time_val: float,
        behavioral_features: dict,
        block_threshold: Optional[float] = None,
        review_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Run the full scoring pipeline for one transaction.

        Steps:
        1. Apply StandardScaler to Amount + Time (V1-V28 unchanged)
        2. Build feature vector (V1-V28 + scaled_Amount + scaled_Time + behavioral)
        3. XGBoost P(fraud)
        4. Isolation Forest normalized score
        5. Fuse: 0.70 * XGB + 0.30 * IF
        6. Apply tiered threshold decision

        Args:
            v_features: List of 28 PCA feature values [V1...V28]
            amount: Original (pre-scaling) transaction amount
            time_val: Original (pre-scaling) Time value
            behavioral_features: Dict with 6 behavioral feature values
            block_threshold: Override block threshold (uses live DB value if None)
            review_threshold: Override review threshold (uses live DB value if None)

        Returns:
            dict: xgb_score, if_score, final_score, decision_tier
        """
        if not self._loaded:
            raise RuntimeError("ScoringService.load() must be called before scoring.")

        bt = block_threshold if block_threshold is not None else self._block_threshold
        rt = review_threshold if review_threshold is not None else self._review_threshold

        # Scale Amount and Time using fitted StandardScaler
        import pandas as pd
        scaler_input = pd.DataFrame([[amount, time_val]], columns=["Amount", "Time"])
        scaled = self.scaler.transform(scaler_input)
        amount_scaled = float(scaled[0, 0])
        time_scaled = float(scaled[0, 1])

        # Build feature vector
        feature_vec = self._build_feature_vector(v_features, amount_scaled, time_scaled, behavioral_features)

        # XGBoost probability
        xgb_prob = float(self.xgb_model.predict_proba(feature_vec)[0, 1])

        # Isolation Forest normalized score
        if_raw = float(self.iso_forest.score_samples(feature_vec)[0])
        if_neg = -if_raw
        if self.if_score_max > self.if_score_min:
            if_norm = float(np.clip((if_neg - self.if_score_min) / (self.if_score_max - self.if_score_min), 0.0, 1.0))
        else:
            if_norm = 0.0

        # Fuse (thesis: 0.70 XGB + 0.30 IF)
        final_score = float(np.clip(0.70 * xgb_prob + 0.30 * if_norm, 0.0, 1.0))

        # Tiered decision
        if final_score > bt:
            tier = "BLOCK"
        elif final_score >= rt:
            tier = "REVIEW"
        else:
            tier = "APPROVE"

        return {
            "xgb_score": round(xgb_prob, 6),
            "if_score": round(if_norm, 6),
            "if_score_raw": round(if_raw, 6),
            "final_score": round(final_score, 6),
            "decision_tier": tier,
            "feature_vector": feature_vec[0].tolist(),
        }

    def get_shap_explanation(
        self,
        feature_vector: np.ndarray,
        top_n: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Compute SHAP values for one transaction using XGBoost's native pred_contribs.

        Uses booster.predict(dmatrix, pred_contribs=True) — the XGBoost built-in SHAP
        implementation — instead of the shap library, which is incompatible with
        XGBoost 2.0+ base_score format on this environment.

        Args:
            feature_vector: 1D or 2D numpy array of feature values (36 features)
            top_n: Number of top features to return

        Returns:
            List of dicts sorted by |shap_value| descending
        """
        if not self._loaded or self._xgb_booster is None:
            return []

        if feature_vector.ndim == 1:
            feature_vector = feature_vector.reshape(1, -1)

        try:
            import xgboost as xgb
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                dmatrix = xgb.DMatrix(feature_vector, feature_names=self.feature_names if self.feature_names else None)
                # pred_contribs=True returns SHAP values per feature + bias column
                contribs = self._xgb_booster.predict(dmatrix, pred_contribs=True)

            # contribs shape: (1, n_features + 1) — last column is bias/intercept
            sv = contribs[0, :-1]   # exclude bias term
            feature_vals = feature_vector[0]

            contributions = [
                {
                    "feature_name": (self.feature_names[i] if i < len(self.feature_names) else f"f{i}"),
                    "shap_value": round(float(sv[i]), 6),
                    "feature_value": round(float(feature_vals[i]), 6),
                    "direction": "increases_risk" if sv[i] > 0 else "decreases_risk",
                    "rank": 0,
                }
                for i in range(len(sv))
            ]
            contributions.sort(key=lambda x: abs(x["shap_value"]), reverse=True)
            for rank, item in enumerate(contributions[:top_n], start=1):
                item["rank"] = rank

            return contributions[:top_n]
        except Exception as e:
            logger.warning("Native XGBoost SHAP computation failed: %s", e)
            return []


    @property
    def is_loaded(self) -> bool:
        return self._loaded


# Singleton instance
_scoring_service: Optional[ScoringService] = None


def get_scoring_service() -> ScoringService:
    """FastAPI dependency: returns the singleton ScoringService."""
    global _scoring_service
    if _scoring_service is None:
        try:
            from app.core.config import settings
            if (settings.model_dir_path / "xgboost_model.joblib").exists():
                logger.info("Auto-initializing ScoringService singleton from %s", settings.model_dir_path)
                return initialize_scoring_service(settings.model_dir_path)
        except Exception as exc:
            logger.error("Auto-initialization of ScoringService failed: %s", exc)

    if _scoring_service is None:
        raise RuntimeError(
            "ScoringService not initialized. "
            "Ensure backend started successfully (model verification passed)."
        )
    return _scoring_service


def initialize_scoring_service(models_dir: Path) -> ScoringService:
    """Initialize the scoring service singleton. Called once at startup."""
    global _scoring_service
    _scoring_service = ScoringService(models_dir)
    _scoring_service.load()
    return _scoring_service
