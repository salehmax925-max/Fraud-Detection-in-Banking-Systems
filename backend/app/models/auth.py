"""
backend/app/models/auth.py
===========================
SQLAlchemy ORM Models for Authentication & Governance System

Tables:
  1. auth_users          — login accounts (admin / user / ceo)
  2. user_permissions    — per-user permission flags (CEO-managed)
  3. threshold_audit     — log of all threshold changes
  4. governance_audit    — log of all CEO governance actions
  5. system_logs         — system-wide event log
  6. user_preferences    — per-user UI state persistence
"""
from __future__ import annotations

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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Auth Users
# ---------------------------------------------------------------------------

class AuthUser(Base):
    __tablename__ = "auth_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # role values: "admin" | "user" | "ceo"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    permissions: Mapped[Optional["UserPermission"]] = relationship(
        "UserPermission", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    preferences: Mapped[Optional["UserPreference"]] = relationship(
        "UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# 2. User Permissions (CEO-managed)
# ---------------------------------------------------------------------------

class UserPermission(Base):
    __tablename__ = "user_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    can_view_personal_data: Mapped[bool] = mapped_column(Boolean, default=False)
    can_edit_thresholds: Mapped[bool] = mapped_column(Boolean, default=True)
    can_view_all_transactions: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    # Relationship
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="permissions")


# ---------------------------------------------------------------------------
# 3. Threshold Audit
# ---------------------------------------------------------------------------

class ThresholdAudit(Base):
    __tablename__ = "threshold_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_by_username: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_threshold_block: Mapped[float] = mapped_column(Float, nullable=False)
    previous_threshold_review: Mapped[float] = mapped_column(Float, nullable=False)
    new_threshold_block: Mapped[float] = mapped_column(Float, nullable=False)
    new_threshold_review: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 4. Governance Audit Log
# ---------------------------------------------------------------------------

class GovernanceAudit(Base):
    __tablename__ = "governance_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    changed_by: Mapped[str] = mapped_column(String(50), nullable=False)
    target_username: Mapped[str] = mapped_column(String(50), nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # change_type: "role_change" | "permission_change" | "password_reset" | "account_disable"
    previous_value: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 5. System Logs
# ---------------------------------------------------------------------------

class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_level: Mapped[str] = mapped_column(String(10), default="INFO")
    # log_level: "INFO" | "WARNING" | "ERROR"
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # event_type: "login_success" | "login_failure" | "logout" | "transaction_submitted"
    #              "threshold_changed" | "role_changed" | "csv_export" | "access_denied"
    username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, name="metadata")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), index=True
    )


# ---------------------------------------------------------------------------
# 6. User Preferences (dashboard state memory)
# ---------------------------------------------------------------------------

class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    last_date_filter: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_tab: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ui_preferences: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    # Relationship
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="preferences")
