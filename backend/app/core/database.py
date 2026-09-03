"""
backend/app/core/database.py
==============================
Async PostgreSQL database setup via SQLAlchemy + asyncpg.

Includes startup schema verification to detect missing columns early.
Neon PostgreSQL: SSL is automatically enabled when the host contains 'neon.tech'.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_async_engine_url(raw_url: str) -> str:
    """
    Convert a raw DATABASE_URL to the asyncpg-compatible format.

    Handles:
    - postgresql:// → postgresql+asyncpg://
    - postgresql+psycopg2:// → postgresql+asyncpg://
    - Neon URLs with ?sslmode=require → removed (asyncpg uses connect_args instead)
    """
    import re
    # Normalize driver prefix
    url = re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", raw_url)
    # Remove sslmode query param — handled via connect_args below
    url = re.sub(r"[?&]sslmode=[^&]*", "", url).rstrip("?&")
    return url


def _requires_ssl(url: str) -> bool:
    """Return True if the database URL points to a cloud service requiring SSL (Neon, RDS, etc.)."""
    ssl_hosts = ["neon.tech", ".rds.amazonaws.com", "supabase.co", "planetscale.com", "cockroachlabs.cloud"]
    return any(h in url for h in ssl_hosts) or "sslmode=require" in url


_raw_db_url = settings.DATABASE_URL
_async_url = _build_async_engine_url(_raw_db_url)
_use_ssl = _requires_ssl(_raw_db_url)

_connect_args: dict = {}
if _use_ssl:
    import ssl as _ssl_mod
    _ssl_ctx = _ssl_mod.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl_mod.CERT_NONE  # Neon uses valid certs; CERT_NONE avoids CA bundle issues
    _connect_args = {"ssl": _ssl_ctx}
    logger.info("Database SSL enabled (Neon/cloud host detected)")

# Create async engine
engine = create_async_engine(
    _async_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=_connect_args,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency: yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    """Create all tables (used at startup instead of Alembic for simplicity)."""
    async with engine.begin() as conn:
        from app.models import orm  # noqa: F401 — ensures models are imported
        from app.models import auth  # noqa: F401 — ensures auth models are imported
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified.")


async def verify_schema_columns() -> None:
    """
    Startup schema verification + auto-migration gate.

    Checks that all required columns exist in the 'transactions' table.
    If any are missing, they are AUTOMATICALLY ADDED via ALTER TABLE so the
    app never fails at runtime with UndefinedColumnError.

    This permanently fixes:
      UndefinedColumnError: column "true_label" of relation "transactions" does not exist
    """
    # Column name → DDL type used in ALTER TABLE ADD COLUMN
    REQUIRED_TRANSACTION_COLUMNS: dict[str, str] = {
        "transaction_uuid":       "VARCHAR(36)",
        "user_id":                "INTEGER",
        "synthetic_user_id":      "VARCHAR(50)",
        "time_val":               "FLOAT",
        "amount":                 "FLOAT",
        "v_features":             "JSON",
        "tx_freq_1h":             "FLOAT",
        "tx_freq_24h":            "FLOAT",
        "amount_deviation_z":     "FLOAT",
        "time_of_day_risk":       "INTEGER",
        "velocity_change":        "FLOAT",
        "location_entropy":       "INTEGER",
        "xgb_score":              "FLOAT",
        "if_score":               "FLOAT",
        "final_score":            "FLOAT",
        "decision_tier":          "VARCHAR(10)",
        "is_simulation":          "BOOLEAN DEFAULT FALSE",
        "true_label":             "INTEGER DEFAULT NULL",   # ← critical fix
        "created_at":             "TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
    }

    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'transactions'
                    AND table_schema = 'public'
                """)
            )
            existing_columns = {row[0] for row in result.fetchall()}

        if not existing_columns:
            logger.warning(
                "⚠️  Schema check: 'transactions' table not found or has no columns. "
                "The table will be created by SQLAlchemy on startup."
            )
            return

        missing = {col: ddl for col, ddl in REQUIRED_TRANSACTION_COLUMNS.items()
                   if col not in existing_columns}

        if missing:
            logger.warning(
                "⚠️  SCHEMA MISMATCH — missing columns detected: %s — auto-applying ALTER TABLE ...",
                list(missing.keys()),
            )
            async with engine.begin() as conn:
                for col, ddl in missing.items():
                    await conn.execute(
                        text(f"ALTER TABLE transactions ADD COLUMN IF NOT EXISTS {col} {ddl}")
                    )
                    logger.info("  ✓ Added column: transactions.%s %s", col, ddl)
            logger.info("✅ Auto-migration complete — all missing columns have been added.")
        else:
            logger.info(
                "✓ Schema verification passed — all %d required columns present in 'transactions'.",
                len(REQUIRED_TRANSACTION_COLUMNS),
            )

    except Exception as e:
        logger.warning("Schema verification could not run (DB may not be up yet): %s", e)


async def dispose_engine() -> None:
    """Dispose the engine connection pool (called at shutdown)."""
    await engine.dispose()
    logger.info("Database engine disposed.")
