"""
Quick diagnostic + seed script.
Run from the backend directory:
  ..\.venv\Scripts\python check_and_seed.py
"""
import asyncio
import os
import sys

sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')

from app.core.config import settings

# Force 127.0.0.1 to avoid IPv6 (::1) issues on Windows
DB_URL = settings.DATABASE_URL.replace('localhost', '127.0.0.1')

async def main():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    import bcrypt

    def hash_pw(pw: str) -> str:
        return bcrypt.hashpw(pw.encode('utf-8')[:72], bcrypt.gensalt(12)).decode('utf-8')

    engine = create_async_engine(DB_URL, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print(f"Connecting to: {DB_URL.split('@')[-1]}")

    async with engine.begin() as conn:
        # Create tables if missing
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auth_users (
                id            SERIAL PRIMARY KEY,
                username      VARCHAR(50) UNIQUE NOT NULL,
                display_name  VARCHAR(100) NOT NULL,
                password_hash VARCHAR(256) NOT NULL,
                role          VARCHAR(20) NOT NULL DEFAULT 'user',
                is_active     BOOLEAN DEFAULT TRUE,
                created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                last_login    TIMESTAMP WITH TIME ZONE
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_permissions (
                id                          SERIAL PRIMARY KEY,
                user_id                     INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
                can_view_personal_data      BOOLEAN DEFAULT FALSE,
                can_edit_thresholds         BOOLEAN DEFAULT TRUE,
                can_view_all_transactions   BOOLEAN DEFAULT FALSE,
                updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(user_id)
            )
        """))
        print("Tables created/verified.")

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

    async with Session() as s:
        # Check existing users
        result = await s.execute(text("SELECT username, role FROM auth_users"))
        existing = {row[0] for row in result.fetchall()}
        print(f"Existing users: {existing if existing else 'NONE'}")

        for u in SEED_USERS:
            new_hash = hash_pw(u["password"])
            if u["username"] in existing:
                await s.execute(
                    text("UPDATE auth_users SET password_hash = :h, role = :role, is_active = TRUE WHERE username = :un"),
                    {"h": new_hash, "role": u["role"], "un": u["username"]}
                )
                print(f"  Updated password hash for: {u['username']}")
            else:
                result = await s.execute(
                    text("""
                        INSERT INTO auth_users (username, display_name, password_hash, role)
                        VALUES (:un, :dn, :ph, :role) RETURNING id
                    """),
                    {"un": u["username"], "dn": u["display_name"], "ph": new_hash, "role": u["role"]}
                )
                new_id = result.scalar()
                await s.execute(
                    text("""
                        INSERT INTO user_permissions (user_id, can_view_personal_data, can_edit_thresholds, can_view_all_transactions)
                        VALUES (:uid, :personal, :thresh, :all_tx)
                        ON CONFLICT (user_id) DO NOTHING
                    """),
                    {
                        "uid": new_id,
                        "personal": u["role"] in ("admin", "ceo"),
                        "thresh": u["role"] != "ceo",
                        "all_tx": u["role"] == "admin",
                    }
                )
                print(f"  Created: {u['username']} ({u['role']})")

        await s.commit()

    # Verify passwords work
    print("\nVerifying passwords...")
    async with Session() as s:
        for u in SEED_USERS:
            r = await s.execute(text("SELECT password_hash FROM auth_users WHERE username = :un"), {"un": u["username"]})
            row = r.fetchone()
            if row:
                ok = bcrypt.checkpw(u["password"].encode('utf-8')[:72], row[0].encode('utf-8'))
                status = "OK" if ok else "FAIL"
                print(f"  {u['username']:<10} password check: {status}")
            else:
                print(f"  {u['username']:<10} NOT FOUND in DB!")

    await engine.dispose()
    print("\nDone! Try logging in now.")

asyncio.run(main())
