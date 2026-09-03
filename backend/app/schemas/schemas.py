"""
backend/app/schemas/schemas.py
================================
Pydantic v2 request/response schemas for all API endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Transaction Scoring
# ---------------------------------------------------------------------------

class ScoreRequest(BaseModel):
    """
    POST /api/score — Transaction payload to score.
    Matches the ULB dataset structure + optional live metadata.
    """
    # ULB dataset fields
    time_val: float = Field(..., description="Time in seconds since dataset start (or Unix epoch for live txns)", ge=0)
    amount: float = Field(..., description="Transaction amount (original, pre-scaling)", ge=0)

    # PCA features V1-V28
    v1: float = Field(default=0.0); v2: float = Field(default=0.0)
    v3: float = Field(default=0.0); v4: float = Field(default=0.0)
    v5: float = Field(default=0.0); v6: float = Field(default=0.0)
    v7: float = Field(default=0.0); v8: float = Field(default=0.0)
    v9: float = Field(default=0.0); v10: float = Field(default=0.0)
    v11: float = Field(default=0.0); v12: float = Field(default=0.0)
    v13: float = Field(default=0.0); v14: float = Field(default=0.0)
    v15: float = Field(default=0.0); v16: float = Field(default=0.0)
    v17: float = Field(default=0.0); v18: float = Field(default=0.0)
    v19: float = Field(default=0.0); v20: float = Field(default=0.0)
    v21: float = Field(default=0.0); v22: float = Field(default=0.0)
    v23: float = Field(default=0.0); v24: float = Field(default=0.0)
    v25: float = Field(default=0.0); v26: float = Field(default=0.0)
    v27: float = Field(default=0.0); v28: float = Field(default=0.0)

    # Optional metadata
    synthetic_user_id: Optional[str] = Field(
        None,
        description="Synthetic user ID. If not provided, generated from time+amount hash. "
                    "SYNTHETIC PROXY — see README About the Dataset."
    )
    device_marker: Optional[str] = Field(None, description="Device/region identifier (synthetic in demo)")
    true_label: Optional[int] = Field(None, ge=0, le=1, description="Known ground truth (for simulation replay only)")

    def get_v_features_dict(self) -> Dict[str, float]:
        """Return V1-V28 as a dict {V1: val, V2: val, ...}"""
        return {f"V{i}": getattr(self, f"v{i}") for i in range(1, 29)}

    def get_v_features_list(self) -> List[float]:
        """Return V1-V28 as ordered list [v1, v2, ..., v28]"""
        return [getattr(self, f"v{i}") for i in range(1, 29)]


class ShapFeature(BaseModel):
    feature_name: str
    shap_value: float
    feature_value: float
    direction: str  # "increases_risk" | "decreases_risk"
    rank: int


class ScoreResponse(BaseModel):
    """Response from POST /api/score"""
    transaction_id: int
    transaction_uuid: str
    synthetic_user_id: str

    # Raw model scores
    xgb_score: float = Field(..., description="XGBoost P(fraud) [0,1]")
    if_score: float = Field(..., description="Isolation Forest normalized score [0,1]")
    final_score: float = Field(..., description="Fused score: 0.70*XGB + 0.30*IF [0,1]")

    # Decision
    decision_tier: str = Field(..., description="BLOCK | REVIEW | APPROVE")

    # Behavioral features computed for this transaction
    behavioral_features: Dict[str, float]

    # SHAP explanation (only populated if final_score >= 0.50)
    shap_explanations: Optional[List[ShapFeature]] = None

    # Metadata
    is_simulation: bool = False
    true_label: Optional[int] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Transaction List & Detail
# ---------------------------------------------------------------------------

class TransactionListItem(BaseModel):
    """Compact transaction record for list views."""
    id: int
    transaction_uuid: str
    synthetic_user_id: str
    amount: float
    time_val: float
    final_score: Optional[float]
    xgb_score: Optional[float]
    if_score: Optional[float]
    decision_tier: Optional[str]
    is_simulation: bool
    true_label: Optional[int] = None  # 0=legitimate, 1=fraud (simulation rows only)
    import_batch_id: Optional[int] = None  # set for CSV-imported rows; NULL for live/simulation
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionDetail(TransactionListItem):
    """Full transaction detail including all features and SHAP."""
    v_features: Dict[str, float] = {}
    tx_freq_1h: Optional[float] = None
    tx_freq_24h: Optional[float] = None
    amount_deviation_z: Optional[float] = None
    time_of_day_risk: Optional[int] = None
    velocity_change: Optional[float] = None
    location_entropy: Optional[int] = None
    shap_explanations: List[ShapFeature] = []
    review_status: Optional[str] = None  # pending | approved | rejected | None

    model_config = {"from_attributes": True}


class PaginatedTransactions(BaseModel):
    items: List[TransactionListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ---------------------------------------------------------------------------
# Review Queue
# ---------------------------------------------------------------------------

class ReviewQueueItem(BaseModel):
    """Item in the analyst review queue."""
    id: int  # ReviewQueue.id
    transaction_id: int
    transaction_uuid: str
    synthetic_user_id: str
    amount: float
    final_score: float
    xgb_score: float
    if_score: float
    status: str  # pending | approved | rejected
    analyst_note: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    shap_explanations: List[ShapFeature] = []

    model_config = {"from_attributes": True}


class ReviewDecisionRequest(BaseModel):
    """POST /api/review-queue/{id}/decision"""
    decision: str = Field(..., description="approved | rejected")
    analyst_note: Optional[str] = Field(None, max_length=1000)

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in ("approved", "rejected"):
            raise ValueError("decision must be 'approved' or 'rejected'")
        return v


class ReviewDecisionResponse(BaseModel):
    id: int
    transaction_id: int
    status: str
    analyst_note: Optional[str]
    reviewed_at: datetime


# ---------------------------------------------------------------------------
# Digital Twin Profile
# ---------------------------------------------------------------------------

class AmountStats(BaseModel):
    count: int
    mean: float
    std: float


class DigitalTwinSummary(BaseModel):
    """Response from GET /api/digital-twin/{user_id}"""
    user_id: str
    total_transactions: int
    amount_stats: AmountStats
    known_devices: List[str]
    known_device_count: int
    recent_transactions: List[Dict[str, Any]] = []
    current_risk_trend: Optional[float] = None
    last_24h_tx_count: int = 0
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Admin Thresholds
# ---------------------------------------------------------------------------

class ThresholdRead(BaseModel):
    id: int
    block_threshold: float
    review_threshold: float
    updated_at: datetime
    updated_by: Optional[str] = None
    # Audit trail fields — populated from threshold_audit table
    last_updated_display_name: Optional[str] = None
    last_updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ThresholdUpdate(BaseModel):
    block_threshold: float = Field(..., ge=0.0, le=1.0, description="Block tier threshold (default 0.85)")
    review_threshold: float = Field(..., ge=0.0, le=1.0, description="Review tier threshold (default 0.50)")
    updated_by: Optional[str] = Field(None, max_length=100)

    @field_validator("block_threshold")
    @classmethod
    def block_must_exceed_review(cls, v: float, info) -> float:
        review = info.data.get("review_threshold")
        if review is not None and v <= review:
            raise ValueError("block_threshold must be greater than review_threshold")
        return v


# ---------------------------------------------------------------------------
# Model Performance Metrics
# ---------------------------------------------------------------------------

class ConfusionMatrix(BaseModel):
    true_negatives: int
    false_positives: int
    false_negatives: int
    true_positives: int


class ModelMetrics(BaseModel):
    model: str
    threshold: float
    precision: float
    recall: float
    f1_score: float
    roc_auc: float
    mcc: float
    confusion_matrix: ConfusionMatrix


class RocCurveData(BaseModel):
    fpr: List[float]
    tpr: List[float]
    auc: float


class MetricsResponse(BaseModel):
    """Response from GET /api/metrics"""
    evaluation_version: str
    test_set_size: int
    test_fraud_count: int
    test_fraud_pct: float
    primary_metrics: Dict[str, Any]
    block_tier_metrics: Dict[str, Any]
    model_comparison: Dict[str, Any]
    roc_curve_data: Dict[str, Any]
    precision_recall_curve_data: Dict[str, Any]
    decision_thresholds: Dict[str, float]


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

class SimulationResponse(BaseModel):
    """Response from GET /api/simulate — test set replay"""
    message: str = "Test Set Replay — these are REAL rows from the held-out test split, scored live."
    disclaimer: str = (
        "These transactions come from the ULB dataset test split. "
        "They are not live bank traffic. This endpoint is for demo purposes only."
    )
    scored_count: int
    transactions: List[ScoreResponse]
