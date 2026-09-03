"""
backend/app/api/history_routes.py
===================================
Transaction history + system logs endpoints:
  GET  /api/history/transactions   — paginated history (role-gated)
  GET  /api/history/export-csv     — CSV export (role-gated)
  GET  /api/logs                   — system event log (admin only)
  GET  /api/preferences            — get user UI preferences
  PUT  /api/preferences            — save user UI preferences
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.auth import AuthUser, SystemLog, UserPreference
from app.models.orm import Transaction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["History & Logs"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TransactionHistoryItem(BaseModel):
    id: int
    transaction_uuid: str
    synthetic_user_id: Optional[str] = None
    auth_user_id: Optional[int] = None
    amount: float
    decision_tier: Optional[str] = None
    xgb_score: Optional[float] = None
    if_score: Optional[float] = None
    final_score: Optional[float] = None
    is_simulation: bool
    true_label: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedHistory(BaseModel):
    items: list[TransactionHistoryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class SystemLogEntry(BaseModel):
    id: int
    log_level: str
    event_type: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PreferencesRequest(BaseModel):
    last_date_filter: Optional[str] = None
    last_tab: Optional[str] = None
    ui_preferences: Optional[dict] = None


# ---------------------------------------------------------------------------
# GET /api/history/transactions
# ---------------------------------------------------------------------------

@router.get("/history/transactions", response_model=PaginatedHistory)
async def get_transaction_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    decision_tier: Optional[str] = Query(None, description="BLOCK | REVIEW | APPROVE"),
    min_amount: Optional[float] = Query(None, ge=0),
    max_amount: Optional[float] = Query(None, ge=0),
    date_from: Optional[str] = Query(None, description="ISO date string e.g. 2026-01-01"),
    date_to: Optional[str] = Query(None, description="ISO date string e.g. 2026-12-31"),
    filter_user_id: Optional[int] = Query(None, description="Admin only: filter by auth_user_id"),
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
) -> PaginatedHistory:
    """
    Paginated transaction history.
    - Admins see ALL transactions (can filter by user)
    - Normal users see ONLY their own transactions
    """
    conditions = []

    # Role-based data scoping
    if current_user.role == "user":
        # Normal users see only their own transactions
        conditions.append(Transaction.user_id == current_user.id)
    elif current_user.role == "admin" and filter_user_id:
        conditions.append(Transaction.user_id == filter_user_id)

    # Decision tier filter
    if decision_tier:
        tier = decision_tier.upper()
        if tier not in ("BLOCK", "REVIEW", "APPROVE"):
            raise HTTPException(status_code=400, detail="decision_tier must be BLOCK, REVIEW, or APPROVE")
        conditions.append(Transaction.decision_tier == tier)

    # Amount range filter
    if min_amount is not None:
        conditions.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        conditions.append(Transaction.amount <= max_amount)

    # Date range filter
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            conditions.append(Transaction.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format")
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
            conditions.append(Transaction.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format")

    # Build query
    base_q = select(Transaction)
    if conditions:
        base_q = base_q.where(and_(*conditions))

    # Count total
    count_q = select(func.count()).select_from(base_q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    items_result = await db.execute(
        base_q.order_by(Transaction.created_at.desc()).offset(offset).limit(page_size)
    )
    transactions = items_result.scalars().all()

    items = []
    for tx in transactions:
        item = TransactionHistoryItem(
            id=tx.id,
            transaction_uuid=tx.transaction_uuid,
            amount=tx.amount,
            decision_tier=tx.decision_tier,
            final_score=tx.final_score,
            is_simulation=tx.is_simulation,
            created_at=tx.created_at,
        )
        # Admin-only fields
        if current_user.role == "admin":
            item.synthetic_user_id = tx.synthetic_user_id
            item.auth_user_id = tx.user_id
            item.xgb_score = tx.xgb_score
            item.if_score = tx.if_score
            item.true_label = tx.true_label
        items.append(item)

    return PaginatedHistory(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


# ---------------------------------------------------------------------------
# GET /api/history/export-csv
# ---------------------------------------------------------------------------

@router.get("/history/export-csv")
async def export_transactions_csv(
    decision_tier: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
) -> StreamingResponse:
    """
    Export transaction history as CSV.
    Admins export all, normal users export only their own.
    """
    conditions = []

    if current_user.role == "user":
        conditions.append(Transaction.user_id == current_user.id)

    if decision_tier:
        conditions.append(Transaction.decision_tier == decision_tier.upper())

    if date_from:
        try:
            conditions.append(Transaction.created_at >= datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    if date_to:
        try:
            conditions.append(Transaction.created_at <= datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc))
        except ValueError:
            pass

    q = select(Transaction)
    if conditions:
        q = q.where(and_(*conditions))
    q = q.order_by(Transaction.created_at.desc())

    result = await db.execute(q)
    transactions = result.scalars().all()

    # Log the export event
    log = SystemLog(
        log_level="INFO",
        event_type="csv_export",
        username=current_user.username,
        display_name=current_user.display_name,
        description=f"{current_user.display_name} exported {len(transactions)} transactions to CSV",
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)
    await db.flush()

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    if current_user.role == "admin":
        writer.writerow([
            "ID", "Transaction UUID", "Synthetic User ID", "Amount",
            "Decision", "XGB Score", "IF Score", "Final Score",
            "Is Simulation", "True Label", "Created At"
        ])
        for tx in transactions:
            writer.writerow([
                tx.id, tx.transaction_uuid, tx.synthetic_user_id, tx.amount,
                tx.decision_tier, tx.xgb_score, tx.if_score, tx.final_score,
                tx.is_simulation, tx.true_label, tx.created_at.isoformat()
            ])
    else:
        writer.writerow([
            "Transaction UUID", "Amount", "Decision", "Final Score", "Created At"
        ])
        for tx in transactions:
            writer.writerow([
                tx.transaction_uuid, tx.amount, tx.decision_tier,
                tx.final_score, tx.created_at.isoformat()
            ])

    output.seek(0)
    filename = f"transactions_{current_user.username}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# GET /api/logs
# ---------------------------------------------------------------------------

@router.get("/logs", response_model=list[SystemLogEntry])
async def get_system_logs(
    limit: int = Query(100, ge=1, le=500),
    event_type: Optional[str] = Query(None),
    log_level: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _admin: AuthUser = Depends(require_admin),
) -> list[SystemLogEntry]:
    """System event log — admin only."""
    q = select(SystemLog).order_by(SystemLog.created_at.desc()).limit(limit)

    conditions = []
    if event_type:
        conditions.append(SystemLog.event_type == event_type)
    if log_level:
        conditions.append(SystemLog.log_level == log_level.upper())
    if conditions:
        q = q.where(and_(*conditions))

    result = await db.execute(q)
    logs = result.scalars().all()
    return [SystemLogEntry.model_validate(log) for log in logs]


# ---------------------------------------------------------------------------
# GET /api/preferences
# ---------------------------------------------------------------------------

@router.get("/preferences")
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
) -> dict:
    """Get saved UI preferences for the current user."""
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        return {"last_date_filter": None, "last_tab": None, "ui_preferences": {}}

    return {
        "last_date_filter": pref.last_date_filter,
        "last_tab": pref.last_tab,
        "ui_preferences": pref.ui_preferences or {},
    }


# ---------------------------------------------------------------------------
# PUT /api/preferences
# ---------------------------------------------------------------------------

@router.put("/preferences")
async def save_preferences(
    body: PreferencesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
) -> dict:
    """Save UI preferences for the current user."""
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = UserPreference(user_id=current_user.id)
        db.add(pref)

    if body.last_date_filter is not None:
        pref.last_date_filter = body.last_date_filter
    if body.last_tab is not None:
        pref.last_tab = body.last_tab
    if body.ui_preferences is not None:
        pref.ui_preferences = body.ui_preferences
    pref.updated_at = datetime.now(timezone.utc)

    await db.flush()
    return {"message": "Preferences saved"}
