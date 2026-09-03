"""
run_migration.py - Adds missing true_label column to transactions table.
Run: ..\.venv\Scripts\python run_migration.py
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(".env")

db_url = os.environ.get("DATABASE_URL", "")
clean = db_url.replace("postgresql+asyncpg://", "").replace("postgresql://", "")
userpass, hostdbname = clean.split("@")
user, password = userpass.split(":", 1)
hostport, dbname = hostdbname.split("/", 1)
host, port = (hostport.split(":", 1) if ":" in hostport else (hostport, "5432"))

print(f"Connecting to {host}:{port}/{dbname} as {user}...")
conn = psycopg2.connect(host=host, port=int(port), dbname=dbname, user=user, password=password)
conn.autocommit = True
cur = conn.cursor()

# --- CRITICAL FIX: Add missing true_label column ---
print("Adding true_label column to transactions (if missing)...")
cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS true_label INTEGER DEFAULT NULL;")
print("  Done.")

# Also add any other potentially missing columns
other_columns = [
    ("transaction_uuid",    "VARCHAR(36)"),
    ("synthetic_user_id",   "VARCHAR(50)"),
    ("time_val",            "FLOAT"),
    ("amount",              "FLOAT"),
    ("tx_freq_1h",          "FLOAT"),
    ("tx_freq_24h",         "FLOAT"),
    ("amount_deviation_z",  "FLOAT"),
    ("time_of_day_risk",    "INTEGER"),
    ("velocity_change",     "FLOAT"),
    ("location_entropy",    "INTEGER"),
    ("xgb_score",           "FLOAT"),
    ("if_score",            "FLOAT"),
    ("final_score",         "FLOAT"),
    ("decision_tier",       "VARCHAR(10)"),
    ("is_simulation",       "BOOLEAN DEFAULT FALSE"),
    ("created_at",          "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
]
for col, col_type in other_columns:
    cur.execute(f"ALTER TABLE transactions ADD COLUMN IF NOT EXISTS {col} {col_type};")

print("All columns checked/added.")

# Verify
cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'transactions'
    ORDER BY ordinal_position
""")
rows = cur.fetchall()
print(f"\nFinal transactions columns ({len(rows)} total):")
for r in rows:
    print(f"  {r[0]:<30} {r[1]}")

cur.close()
conn.close()
print("\nMigration complete! You can now run simulations.")
