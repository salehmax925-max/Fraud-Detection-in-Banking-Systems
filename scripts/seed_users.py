#!/usr/bin/env python
"""
scripts/seed_users.py
======================
Standalone script to seed the 5 auth users into the database.

Usage:
    python scripts/seed_users.py

Run from the project root directory (graduation project/).
The script uses the same DATABASE_URL as the backend.

This is an alternative to the automatic seeding that happens
when the FastAPI backend starts. Use this if you need to seed
users without starting the full backend.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add backend to path
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fraud:fraud_pass@localhost:5432/frauddb")

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://fraud:fraud_pass@localhost:5432/frauddb")

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode('utf-8')[:72], bcrypt.gensalt(12)).decode('utf-8')

SEED_USERS = [
    {"username": "admin",   "display_name": "Amin",                 "role": "admin", "password": "2004"},
    {"username": "saleh",   "display_name": "Saleh Ghannmah",      "role": "admin", "password": "2004"},
    {"username": "amin",    "display_name": "Amin",                 "role": "admin", "password": "2004"},
    {"username": "hussein", "display_name": "Hussein Al-Ahmer",    "role": "user",  "password": "2004"},
    {"username": "ali",     "display_name": "Ali Nasser",          "role": "user",  "password": "2004"},
    {"username": "user1",   "display_name": "User One",            "role": "user",  "password": "2004"},
    {"username": "user2",   "display_name": "User Two",            "role": "user",  "password": "2004"},
    {"username": "hussain", "display_name": "Hussain (CEO)",       "role": "ceo",   "password": "2004"},
    {"username": "ceo",     "display_name": "Data Manager (CEO)",  "role": "ceo",   "password": "2004"},
]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS auth_users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50) UNIQUE NOT NULL,
    display_name  VARCHAR(100) NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    role          VARCHAR(20) NOT NULL DEFAULT 'user',
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login    TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS user_permissions (
    id                          SERIAL PRIMARY KEY,
    user_id                     INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
    can_view_personal_data      BOOLEAN DEFAULT FALSE,
    can_edit_thresholds         BOOLEAN DEFAULT TRUE,
    can_view_all_transactions   BOOLEAN DEFAULT FALSE,
    updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);
"""

async def seed():
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            from sqlalchemy import text
            for stmt in CREATE_TABLE_SQL.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))
        print("✓ Tables created/verified")

        from sqlalchemy import text
        async with SessionLocal() as session:
            for user_data in SEED_USERS:
                result = await session.execute(
                    text("SELECT id FROM auth_users WHERE username = :username"),
                    {"username": user_data["username"]}
                )
                existing = result.scalar_one_or_none()

                if existing is None:
                    hashed = hash_pw(user_data["password"])
                    result = await session.execute(
                        text("""
                            INSERT INTO auth_users (username, display_name, password_hash, role)
                            VALUES (:username, :display_name, :password_hash, :role)
                            RETURNING id
                        """),
                        {
                            "username": user_data["username"],
                            "display_name": user_data["display_name"],
                            "password_hash": hashed,
                            "role": user_data["role"],
                        }
                    )
                    new_id = result.scalar()

                    # Insert default permissions
                    admin_roles = ("admin", "ceo")
                    await session.execute(
                        text("""
                            INSERT INTO user_permissions
                              (user_id, can_view_personal_data, can_edit_thresholds, can_view_all_transactions)
                            VALUES (:user_id, :personal, :thresholds, :all_tx)
                            ON CONFLICT (user_id) DO NOTHING
                        """),
                        {
                            "user_id": new_id,
                            "personal": user_data["role"] in admin_roles,
                            "thresholds": user_data["role"] != "ceo",
                            "all_tx": user_data["role"] == "admin",
                        }
                    )
                    print(f"  ✓ Created: {user_data['username']} ({user_data['role']})")
                else:
                    print(f"  ─ Skipped: {user_data['username']} (already exists)")

            await session.commit()

        print("\n✅ Seeding complete!")
        print("\nLogin credentials:")
        print("-" * 50)
        for u in SEED_USERS:
            print(f"  {u['username']:<10} | {u['role']:<6} | {u['password']}")
        print("-" * 50)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
