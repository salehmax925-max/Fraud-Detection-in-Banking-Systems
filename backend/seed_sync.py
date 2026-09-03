"""
Seed auth users using psycopg2 (synchronous, no asyncpg issues).
Run: ..\.venv\Scripts\python seed_sync.py
"""
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')

import psycopg2
import bcrypt

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode('utf-8')[:72], bcrypt.gensalt(12)).decode('utf-8')

# Build psycopg2 connection params from DATABASE_URL
# Format: postgresql+asyncpg://fraud:fraud_pass@localhost:5432/frauddb
db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://fraud:fraud_pass@localhost:5432/frauddb")
# Strip the driver prefix
clean = db_url.replace("postgresql+asyncpg://", "").replace("postgresql://", "")
# Parse: user:pass@host:port/dbname
userpass, hostdbname = clean.split("@")
user, password = userpass.split(":", 1)
hostport, dbname = hostdbname.split("/", 1)
if ":" in hostport:
    host, port = hostport.split(":", 1)
else:
    host, port = hostport, "5432"

print(f"Connecting to: {host}:{port}/{dbname} as {user}")

conn = psycopg2.connect(host=host, port=int(port), dbname=dbname, user=user, password=password)
conn.autocommit = False
cur = conn.cursor()

# Create tables
print("Creating tables if not exist...")
cur.execute("""
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
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS user_permissions (
        id                          SERIAL PRIMARY KEY,
        user_id                     INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
        can_view_personal_data      BOOLEAN DEFAULT FALSE,
        can_edit_thresholds         BOOLEAN DEFAULT TRUE,
        can_view_all_transactions   BOOLEAN DEFAULT FALSE,
        updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        UNIQUE(user_id)
    )
""")
conn.commit()
print("Tables OK.")

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

# Check existing
cur.execute("SELECT username FROM auth_users")
existing = {row[0] for row in cur.fetchall()}
print(f"Existing users: {existing if existing else 'NONE'}")

for u in SEED_USERS:
    new_hash = hash_pw(u["password"])
    if u["username"] in existing:
        cur.execute("UPDATE auth_users SET password_hash = %s WHERE username = %s", (new_hash, u["username"]))
        print(f"  Updated hash: {u['username']}")
    else:
        cur.execute(
            "INSERT INTO auth_users (username, display_name, password_hash, role, is_active) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (u["username"], u["display_name"], new_hash, u["role"], True)
        )
        new_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO user_permissions (user_id, can_view_personal_data, can_edit_thresholds, can_view_all_transactions, updated_at)
               VALUES (%s, %s, %s, %s, NOW()) ON CONFLICT (user_id) DO NOTHING""",
            (new_id,
             u["role"] in ("admin", "ceo"),
             u["role"] != "ceo",
             u["role"] == "admin")
        )
        print(f"  Created: {u['username']} ({u['role']})")

conn.commit()

# Verify
print("\nVerifying passwords...")
for u in SEED_USERS:
    cur.execute("SELECT password_hash FROM auth_users WHERE username = %s", (u["username"],))
    row = cur.fetchone()
    if row:
        ok = bcrypt.checkpw(u["password"].encode('utf-8')[:72], row[0].encode('utf-8'))
        print(f"  {u['username']:<10} → {'✓ OK' if ok else '✗ FAIL'}")
    else:
        print(f"  {u['username']:<10} → NOT FOUND!")

cur.close()
conn.close()
print("\nSeeding complete! You can now log in.")
