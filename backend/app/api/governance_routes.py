"""
backend/app/api/governance_routes.py
======================================
CEO-only governance management endpoints:
  GET  /api/governance/users                       — list all auth users
  PUT  /api/governance/users/{id}/role             — change user role
  PUT  /api/governance/users/{id}/permissions      — update permission flags
  POST /api/governance/users/{id}/reset-password   — reset any user's password
  POST /api/governance/users/{id}/toggle-active    — enable/disable account
  GET  /api/governance/audit-log                   — governance change history
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth_deps import require_ceo
from app.core.database import get_db
from app.core.security import hash_password
from app.models.auth import AuthUser, GovernanceAudit, SystemLog, UserPermission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/governance", tags=["Governance (CEO Only)"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UserSummary(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    last_login: Optional[datetime] = None
    permissions: Optional[dict] = None

    model_config = {"from_attributes": True}


class RoleUpdateRequest(BaseModel):
    new_role: str  # "admin" | "user"


class PermissionsUpdateRequest(BaseModel):
    can_view_personal_data: Optional[bool] = None
    can_edit_thresholds: Optional[bool] = None
    can_view_all_transactions: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    new_password: str


class GovernanceAuditEntry(BaseModel):
    id: int
    changed_by: str
    target_username: str
    change_type: str
    previous_value: Optional[str]
    new_value: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helper: create audit log entry
# ---------------------------------------------------------------------------

async def _audit(
    db: AsyncSession,
    changed_by: str,
    target_username: str,
    change_type: str,
    previous_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> None:
    audit = GovernanceAudit(
        changed_by=changed_by,
        target_username=target_username,
        change_type=change_type,
        previous_value=previous_value,
        new_value=new_value,
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)

    system_log = SystemLog(
        log_level="INFO",
        event_type="role_changed" if change_type == "role_change" else "governance_change",
        username=changed_by,
        description=f"CEO changed {target_username}'s {change_type}: {previous_value} → {new_value}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(system_log)
    await db.flush()


# ---------------------------------------------------------------------------
# GET /api/governance/users
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserSummary])
async def list_governance_users(
    db: AsyncSession = Depends(get_db),
    _ceo: AuthUser = Depends(require_ceo),
) -> list[UserSummary]:
    """List all auth users with their permissions and last login."""
    result = await db.execute(
        select(AuthUser)
        .options(selectinload(AuthUser.permissions))
        .order_by(AuthUser.id)
    )
    users = result.scalars().all()

    summaries = []
    for u in users:
        perms = None
        if u.permissions:
            perms = {
                "can_view_personal_data": u.permissions.can_view_personal_data,
                "can_edit_thresholds": u.permissions.can_edit_thresholds,
                "can_view_all_transactions": u.permissions.can_view_all_transactions,
            }
        summaries.append(UserSummary(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            role=u.role,
            is_active=u.is_active,
            last_login=u.last_login,
            permissions=perms,
        ))
    return summaries


# ---------------------------------------------------------------------------
# PUT /api/governance/users/{id}/role
# ---------------------------------------------------------------------------

@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ceo_user: AuthUser = Depends(require_ceo),
) -> dict:
    """Change a user's role. CEO cannot change their own role."""
    if body.new_role not in ("admin", "user"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be 'admin' or 'user'. CEO role cannot be assigned via governance.",
        )

    result = await db.execute(select(AuthUser).where(AuthUser.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.username == ceo_user.username:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    old_role = user.role
    user.role = body.new_role
    await db.flush()

    await _audit(
        db,
        changed_by=ceo_user.username,
        target_username=user.username,
        change_type="role_change",
        previous_value=old_role,
        new_value=body.new_role,
    )

    return {
        "message": f"Role updated: {user.username} → {body.new_role}",
        "username": user.username,
        "new_role": body.new_role,
    }


# ---------------------------------------------------------------------------
# PUT /api/governance/users/{id}/permissions
# ---------------------------------------------------------------------------

@router.put("/users/{user_id}/permissions")
async def update_user_permissions(
    user_id: int,
    body: PermissionsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ceo_user: AuthUser = Depends(require_ceo),
) -> dict:
    """Toggle individual permission flags for a user."""
    result = await db.execute(
        select(AuthUser)
        .options(selectinload(AuthUser.permissions))
        .where(AuthUser.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.permissions is None:
        user.permissions = UserPermission(user_id=user.id)
        db.add(user.permissions)
        await db.flush()

    changes = []
    if body.can_view_personal_data is not None:
        old = user.permissions.can_view_personal_data
        user.permissions.can_view_personal_data = body.can_view_personal_data
        changes.append(f"can_view_personal_data: {old}→{body.can_view_personal_data}")

    if body.can_edit_thresholds is not None:
        old = user.permissions.can_edit_thresholds
        user.permissions.can_edit_thresholds = body.can_edit_thresholds
        changes.append(f"can_edit_thresholds: {old}→{body.can_edit_thresholds}")

    if body.can_view_all_transactions is not None:
        old = user.permissions.can_view_all_transactions
        user.permissions.can_view_all_transactions = body.can_view_all_transactions
        changes.append(f"can_view_all_transactions: {old}→{body.can_view_all_transactions}")

    user.permissions.updated_at = datetime.now(timezone.utc)
    await db.flush()

    if changes:
        await _audit(
            db,
            changed_by=ceo_user.username,
            target_username=user.username,
            change_type="permission_change",
            previous_value="see changes",
            new_value="; ".join(changes),
        )

    return {"message": "Permissions updated", "changes": changes}


# ---------------------------------------------------------------------------
# POST /api/governance/users/{id}/reset-password
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    ceo_user: AuthUser = Depends(require_ceo),
) -> dict:
    """Reset any user's password. Only CEO can do this."""
    result = await db.execute(select(AuthUser).where(AuthUser.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(body.new_password)
    await db.flush()

    await _audit(
        db,
        changed_by=ceo_user.username,
        target_username=user.username,
        change_type="password_reset",
        previous_value="[hashed]",
        new_value="[new hash]",
    )

    return {"message": f"Password reset for {user.username}"}


# ---------------------------------------------------------------------------
# POST /api/governance/users/{id}/toggle-active
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    ceo_user: AuthUser = Depends(require_ceo),
) -> dict:
    """Enable or disable a user account."""
    result = await db.execute(select(AuthUser).where(AuthUser.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.username == ceo_user.username:
        raise HTTPException(status_code=400, detail="Cannot disable your own account")

    old_state = user.is_active
    user.is_active = not user.is_active
    await db.flush()

    await _audit(
        db,
        changed_by=ceo_user.username,
        target_username=user.username,
        change_type="account_disable" if not user.is_active else "account_enable",
        previous_value=str(old_state),
        new_value=str(user.is_active),
    )

    action = "disabled" if not user.is_active else "enabled"
    return {"message": f"Account {action}: {user.username}", "is_active": user.is_active}


# ---------------------------------------------------------------------------
# GET /api/governance/audit-log
# ---------------------------------------------------------------------------

@router.get("/audit-log", response_model=list[GovernanceAuditEntry])
async def get_governance_audit_log(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _ceo: AuthUser = Depends(require_ceo),
) -> list[GovernanceAuditEntry]:
    """Full governance change history — CEO only."""
    result = await db.execute(
        select(GovernanceAudit)
        .order_by(GovernanceAudit.created_at.desc())
        .limit(limit)
    )
    entries = result.scalars().all()
    return [GovernanceAuditEntry.model_validate(e) for e in entries]
