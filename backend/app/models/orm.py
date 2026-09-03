"""
backend/app/models/orm.py
==========================
SQLAlchemy ORM Models — All 6 database tables

Tables:
  1. users                — synthetic user registry
  2. transactions         — scored transaction records
  3. shap_explanations    — per-transaction SHAP feature contributions
  4. review_queue         — analyst review workflow
  5. digital_twin_profiles — per-user behavioral state (JSON rolling stats)
  6. thresholds_config    — live-adjustable scoring thresholds
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    synthetic_user_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="user", lazy="select")
    digital_twin: Mapped[Optional["DigitalTwinProfile"]] = relationship("DigitalTwinProfile", back_populates="user", uselist=False)


# ---------------------------------------------------------------------------
# 2. Transactions
# ---------------------------------------------------------------------------

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_uuid: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    synthetic_user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Raw features (from ULB dataset / transaction submission)
    time_val: Mapped[float] = mapped_column(Float, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)

    # PCA features V1-V28 stored as JSON (avoids 28 columns)
    v_features: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Engineered behavioral features
    tx_freq_1h: Mapped[float] = mapped_column(Float, nullable=True)
    tx_freq_24h: Mapped[float] = mapped_column(Float, nullable=True)
    amount_deviation_z: Mapped[float] = mapped_column(Float, nullable=True)
    time_of_day_risk: Mapped[int] = mapped_column(Integer, nullable=True)
    velocity_change: Mapped[float] = mapped_column(Float, nullable=True)
    location_entropy: Mapped[int] = mapped_column(Integer, nullable=True)

    # Model scores
    xgb_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    if_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    final_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    decision_tier: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)  # BLOCK/REVIEW/APPROVE

    # Is this from the demo simulation replay?
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False)

    # Ground truth label from ULB dataset (simulation rows only): 0=legitimate, 1=fraud
    true_label: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Which CSV import batch produced this row (NULL for live/simulation transactions)
    import_batch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now(), index=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="transactions")
    shap_explanations: Mapped[list["ShapExplanation"]] = relationship("ShapExplanation", back_populates="transaction", cascade="all, delete-orphan")
    review_queue_entry: Mapped[Optional["ReviewQueue"]] = relationship("ReviewQueue", back_populates="transaction", uselist=False)


# ---------------------------------------------------------------------------
# 3. SHAP Explanations
# ---------------------------------------------------------------------------

class ShapExplanation(Base):
    __tablename__ = "shap_explanations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)

    feature_name: Mapped[str] = mapped_column(String(50), nullable=False)
    shap_value: Mapped[float] = mapped_column(Float, nullable=False)
    feature_value: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(30), nullable=False)  # increases_risk / decreases_risk
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationship
    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="shap_explanations")


# ---------------------------------------------------------------------------
# 4. Review Queue
# ---------------------------------------------------------------------------

class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    # status: pending | approved | rejected

    analyst_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())

    # Relationship
    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="review_queue_entry")


# ---------------------------------------------------------------------------
# 5. Digital Twin Profiles
# ---------------------------------------------------------------------------

class DigitalTwinProfile(Base):
    __tablename__ = "digital_twin_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    synthetic_user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Rolling stats stored as JSON (BehavioralFeatureEngine.to_dict())
    rolling_stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="digital_twin")


# ---------------------------------------------------------------------------
# 6. Thresholds Config
# ---------------------------------------------------------------------------

class ThresholdConfig(Base):
    __tablename__ = "thresholds_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    block_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
    review_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.50)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    updated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


# ---------------------------------------------------------------------------
# 7. Import Batches  (CSV Data Import tracking)
# ---------------------------------------------------------------------------

class ImportBatch(Base):
    """
    Tracks each CSV data import operation.
    Created on both validate-only and full import runs.
    """
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # File metadata
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    server_filename: Mapped[str] = mapped_column(String(255), nullable=False)  # UUID-based safe name

    # User who triggered the import
    uploaded_by_username: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Row statistics
    original_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Scoring results (when scored=True)
    scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approve_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    review_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    block_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Processing metadata
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="import")
    # mode: "validate" | "import" | "import_and_score"

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    # status: "pending" | "validating" | "importing" | "completed" | "failed" | "validated_only"

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processing_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

