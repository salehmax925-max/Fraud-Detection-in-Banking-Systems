"""
backend/app/core/config.py
===========================
Application configuration via Pydantic-Settings (reads from .env)
"""
from __future__ import annotations

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

    # Database (127.0.0.1 prevents Windows IPv6 resolution issues)
    DATABASE_URL: str = "postgresql+asyncpg://fraud:fraud_pass@127.0.0.1:5432/frauddb"
    DATABASE_SYNC_URL: str = "postgresql+psycopg2://fraud:fraud_pass@127.0.0.1:5432/frauddb"

    # CORS (frontend dev server)
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Model artifacts
    MODEL_DIR: str = str(_BACKEND_DIR.parent / "models")
    PROCESSED_DATA_DIR: str = str(_BACKEND_DIR.parent / "data" / "processed")
    SKIP_MODEL_VERIFICATION: bool = True  # Set True during development

    # Fraud detection thresholds (defaults — can be updated live via API)
    DEFAULT_BLOCK_THRESHOLD: float = 0.85
    DEFAULT_REVIEW_THRESHOLD: float = 0.50

    # Simulation
    SIMULATION_BATCH_SIZE: int = 20  # rows returned per /api/simulate call

    # Ollama LLM (optional — AI Chat falls back gracefully when offline)
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    @property
    def model_dir_path(self) -> Path:
        return Path(self.MODEL_DIR)

    @property
    def processed_dir_path(self) -> Path:
        return Path(self.PROCESSED_DATA_DIR)


settings = Settings()
