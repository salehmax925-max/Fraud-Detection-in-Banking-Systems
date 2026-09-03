"""
backend/app/core/config.py
===========================
Application configuration via Pydantic-Settings (reads from .env)

Production (Neon PostgreSQL) note:
  Set DATABASE_URL to your Neon connection string:
  postgresql+asyncpg://user:password@host.neon.tech/dbname?sslmode=require
  OR simply: postgresql://user:password@host.neon.tech/dbname?sslmode=require
  The database module will auto-detect Neon and enable SSL.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_NAME: str = "Fraud Detection API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Database
    # Local default: postgresql+asyncpg://fraud:fraud_pass@127.0.0.1:5432/frauddb
    # Neon example: postgresql://user:pass@host.neon.tech/dbname?sslmode=require
    DATABASE_URL: str = "postgresql+asyncpg://fraud:fraud_pass@127.0.0.1:5432/frauddb"
    DATABASE_SYNC_URL: str = "postgresql+psycopg2://fraud:fraud_pass@127.0.0.1:5432/frauddb"

    # CORS (comma-separated list of allowed origins)
    # Regex also allows all *.vercel.app preview deployments (set in main.py)
    CORS_ORIGINS: str = (
        "https://fraudshield-ai.vercel.app,"
        "https://fraudshield-backend1-w1vk.onrender.com,"
        "http://localhost:5173,"
        "http://localhost:3000"
    )

    # Model artifacts
    MODEL_DIR: str = str(_BACKEND_DIR.parent / "models")
    PROCESSED_DATA_DIR: str = str(_BACKEND_DIR.parent / "data" / "processed")

    # Skip checksum verification subprocess (set True in production containers
    # where git CRLF conversion may alter binary checksums).
    # Models still load and validate at runtime via ScoringService.
    SKIP_MODEL_VERIFICATION: bool = True

    # Fraud detection thresholds (defaults — can be updated live via API)
    DEFAULT_BLOCK_THRESHOLD: float = 0.85
    DEFAULT_REVIEW_THRESHOLD: float = 0.50

    # Simulation
    SIMULATION_BATCH_SIZE: int = 20  # rows returned per /api/simulate call

    # Ollama LLM (optional — AI Chat falls back gracefully when offline)
    # Local: http://localhost:11434
    # Remote: http://your-ollama-server:11434
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"

    # JWT Secret (CHANGE IN PRODUCTION — generate with: python -c "import secrets; print(secrets.token_hex(32))")
    SECRET_KEY: str = "fraud-detection-balqa-2026-jwt-secret-change-in-production-use-strong-random-key"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    @property
    def model_dir_path(self) -> Path:
        return Path(self.MODEL_DIR.strip())

    @property
    def processed_dir_path(self) -> Path:
        return Path(self.PROCESSED_DATA_DIR.strip())

    @property
    def database_sync_url_clean(self) -> str:
        """psycopg2-compatible sync URL (strips asyncpg driver prefix)."""
        return re.sub(r"^postgresql\+asyncpg://", "postgresql+psycopg2://", self.DATABASE_SYNC_URL)


settings = Settings()
