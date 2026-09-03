"""
backend/app/api/auth_routes.py
================================
Authentication endpoints:
  POST /api/auth/login   — username/password → JWT cookie
  POST /api/auth/logout  — clears JWT cookie
  GET  /api/auth/me      — returns current user info
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth_deps import get_current_user
from app.core.database import get_db, AsyncSessionLocal
from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    verify_password,
)
from app.models.auth import AuthUser, SystemLog, UserPermission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    last_login: Optional[datetime] = None
    permissions: Optional[dict] = None

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    message: str
    user: UserInfo


# ---------------------------------------------------------------------------
# Helper: log system event
# ---------------------------------------------------------------------------

async def _log_event(
    db: AsyncSession,
    event_type: str,
    username: Optional[str] = None,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    log_level: str = "INFO",
    metadata: Optional[dict] = None,
) -> None:
    log = SystemLog(
        log_level=log_level,
        event_type=event_type,
        username=username,
        display_name=display_name,
        description=description,
        extra_data=metadata,
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)
    await db.flush()


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate user with username and password.
    On success: sets HttpOnly JWT cookie and returns user info.
    On failure: logs the attempt and returns 401.
    """
    # Load user (case-insensitive and trimmed)
    clean_username = credentials.username.strip().lower()
    result = await db.execute(
        select(AuthUser)
        .options(selectinload(AuthUser.permissions))
        .where(func.lower(AuthUser.username) == clean_username)
    )
    user = result.scalar_one_or_none()

    # Verify credentials
    if user is None or not verify_password(credentials.password, user.password_hash):
        await _log_event(
            db,
            event_type="login_failure",
            username=credentials.username,
            description=f"Failed login attempt for username: {credentials.username}",
            log_level="WARNING",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled. Contact the Data Manager.",
        )

    # Update last_login
    user.last_login = datetime.now(timezone.utc)
    await db.flush()

    # Log success
    await _log_event(
        db,
        event_type="login_success",
        username=user.username,
        display_name=user.display_name,
        description=f"{user.display_name} ({user.role}) logged in successfully",
    )

    # Create JWT token
    token = create_access_token(
        data={
            "sub": user.username,
            "role": user.role,
            "display_name": user.display_name,
            "user_id": user.id,
        }
    )

    # Set HttpOnly cookie
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )

    # Build permissions dict
    perms = None
    if user.permissions:
        perms = {
            "can_view_personal_data": user.permissions.can_view_personal_data,
            "can_edit_thresholds": user.permissions.can_edit_thresholds,
            "can_view_all_transactions": user.permissions.can_view_all_transactions,
        }

    logger.info("User '%s' (role=%s) logged in successfully", user.username, user.role)

    return LoginResponse(
        message="Login successful",
        user=UserInfo(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            is_active=user.is_active,
            last_login=user.last_login,
            permissions=perms,
        ),
    )


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------

@router.post("/logout")
async def logout(
    response: Response,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Clear the JWT cookie and log the logout event."""
    await _log_event(
        db,
        event_type="logout",
        username=current_user.username,
        display_name=current_user.display_name,
        description=f"{current_user.display_name} logged out",
    )

    response.delete_cookie(key="access_token", path="/")
    logger.info("User '%s' logged out", current_user.username)
    return {"message": "Logged out successfully"}


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserInfo)
async def get_me(
    current_user: AuthUser = Depends(get_current_user),
) -> UserInfo:
    """Return the currently authenticated user's info."""
    perms = None
    if current_user.permissions:
        perms = {
            "can_view_personal_data": current_user.permissions.can_view_personal_data,
            "can_edit_thresholds": current_user.permissions.can_edit_thresholds,
            "can_view_all_transactions": current_user.permissions.can_view_all_transactions,
        }

    return UserInfo(
        id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        role=current_user.role,
        is_active=current_user.is_active,
        last_login=current_user.last_login,
        permissions=perms,
    )


# ---------------------------------------------------------------------------
# Seed utility (called from main.py on startup)
# ---------------------------------------------------------------------------

async def seed_auth_users() -> None:
    """
    Seed/update predefined auth users so they always have working bcrypt hashes.
    Called once during application startup.

    Default accounts (Password for all: 2004):
      admin   / 2004  → Admin
      saleh   / 2004  → Admin
      amin    / 2004  → Admin
      user1   / 2004  → User
      user2   / 2004  → User
      hussein / 2004  → User
      ali     / 2004  → User
      hussain / 2004  → CEO / Super Admin
      ceo     / 2004  → CEO / Super Admin
    """
    from app.core.security import hash_password, SEED_USER_PASSWORDS

    SEED_USERS = [
        {"username": "admin",   "display_name": "Amin",                 "role": "admin"},
        {"username": "saleh",   "display_name": "Saleh Ghannmah",      "role": "admin"},
        {"username": "amin",    "display_name": "Amin",                 "role": "admin"},
        {"username": "user1",   "display_name": "User One",            "role": "user"},
        {"username": "user2",   "display_name": "User Two",            "role": "user"},
        {"username": "hussein", "display_name": "Hussein Al-Ahmer",    "role": "user"},
        {"username": "ali",     "display_name": "Ali Nasser",          "role": "user"},
        {"username": "hussain", "display_name": "Hussain (CEO)",       "role": "ceo"},
        {"username": "ceo",     "display_name": "Data Manager (CEO)",  "role": "ceo"},
    ]

    async with AsyncSessionLocal() as session:
        for user_data in SEED_USERS:
            existing = await session.execute(
                select(AuthUser)
                .options(selectinload(AuthUser.permissions))
                .where(AuthUser.username == user_data["username"])
            )
            db_user = existing.scalar_one_or_none()
            plain_pw = SEED_USER_PASSWORDS.get(user_data["username"], "2004")
            new_hash = hash_password(plain_pw)

            if db_user is None:
                # Create new user
                new_user = AuthUser(
                    username=user_data["username"],
                    display_name=user_data["display_name"],
                    password_hash=new_hash,
                    role=user_data["role"],
                    is_active=True,
                )
                session.add(new_user)
                await session.flush()

                # Default permissions
                admin_roles = ("admin", "ceo")
                perms = UserPermission(
                    user_id=new_user.id,
                    can_view_personal_data=(user_data["role"] in admin_roles),
                    can_edit_thresholds=(user_data["role"] == "admin"),
                    can_view_all_transactions=(user_data["role"] in admin_roles),
                )
                session.add(perms)
                logger.info("Seeded auth user: %s (%s)", user_data["username"], user_data["role"])
            else:
                # User exists — update password hash and role to match current config
                db_user.password_hash = new_hash
                db_user.role = user_data["role"]
                db_user.display_name = user_data["display_name"]
                db_user.is_active = True
                
                # Ensure permissions exist
                if not db_user.permissions:
                    admin_roles = ("admin", "ceo")
                    perms = UserPermission(
                        user_id=db_user.id,
                        can_view_personal_data=(user_data["role"] in admin_roles),
                        can_edit_thresholds=(user_data["role"] == "admin"),
                        can_view_all_transactions=(user_data["role"] in admin_roles),
                    )
                    session.add(perms)

                logger.info("Updated auth user: %s (%s)", user_data["username"], user_data["role"])

        await session.commit()

    logger.info("Auth user seeding complete.")

