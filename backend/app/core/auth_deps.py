"""
backend/app/core/auth_deps.py
==============================
FastAPI dependency injectors for authentication and role-based access control.

Usage:
    from app.core.auth_deps import get_current_user, require_admin, require_ceo

    @router.get("/admin/thresholds")
    async def get_thresholds(current_user: AuthUser = Depends(require_admin)):
        ...
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.auth import AuthUser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core dependency: extract and validate JWT from cookie
# ---------------------------------------------------------------------------

async def get_current_user(
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthUser:
    """
    FastAPI dependency that:
    1. Reads the JWT from the 'access_token' HttpOnly cookie
    2. Decodes and verifies the token
    3. Loads the AuthUser from DB
    4. Raises 401 if any step fails

    Returns:
        The currently authenticated AuthUser ORM object.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not access_token:
        raise credentials_exception

    payload = decode_access_token(access_token)
    if payload is None:
        raise credentials_exception

    username: Optional[str] = payload.get("sub")
    if username is None:
        raise credentials_exception

    result = await db.execute(
        select(AuthUser)
        .options(selectinload(AuthUser.permissions))
        .where(AuthUser.username == username)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_exception

    return user


async def get_current_user_optional(
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> Optional[AuthUser]:
    """Same as get_current_user but returns None instead of raising 401."""
    if not access_token:
        return None
    try:
        return await get_current_user(access_token=access_token, db=db)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Role-based dependencies
# ---------------------------------------------------------------------------

async def require_admin(
    current_user: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """Requires the user to have role 'admin'. Raises 403 otherwise."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def require_ceo(
    current_user: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """Requires the user to have role 'ceo'. Raises 403 otherwise."""
    if current_user.role != "ceo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied — This area is restricted to the Data Manager.",
        )
    return current_user


async def require_admin_or_user(
    current_user: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """Requires the user to have role 'admin' OR 'user' (not CEO)."""
    if current_user.role not in ("admin", "user"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dashboard access not available for this role",
        )
    return current_user
