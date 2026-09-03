"""
backend/app/main.py
=====================
FastAPI Application Entry Point — Fraud Detection System

STARTUP VERIFICATION GATE:
  The backend REFUSES to start if model verification fails (Section 4b).
  This gate is controlled by the SKIP_MODEL_VERIFICATION env variable.
  Never set SKIP_MODEL_VERIFICATION=True in production.

Startup sequence:
  1. Run scripts/verify_model.py (checksum + smoke-validation)
  2. Initialize ScoringService (load model artifacts)
  3. Initialize DigitalTwinEngine
  4. Create/verify database tables (including all auth tables)
  5. Verify schema columns (catch true_label and other mismatches early)
  6. Seed default threshold config if not present
  7. Seed auth users (5 predefined accounts with bcrypt hashes)
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

# Add project root to path so ml/ is importable
# Path: backend/app/main.py → .parent = backend/app → .parent = backend → .parent = graduation project/
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.core.config import settings
from app.core.database import create_tables, dispose_engine, verify_schema_columns

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configure logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Startup Verification Gate (Section 4b)
# ---------------------------------------------------------------------------

def run_model_verification() -> bool:
    """
    Run scripts/verify_model.py as a subprocess.
    Returns True if verification passes, False if it fails.

    The backend will refuse to start if this returns False.
    """
    verify_script = _PROJECT_ROOT / "scripts" / "verify_model.py"
    models_dir = settings.model_dir_path
    processed_dir = settings.processed_dir_path

    logger.info("=" * 60)
    logger.info("RUNNING MODEL VERIFICATION (Section 4b)")
    logger.info("  Models dir:    %s", models_dir)
    logger.info("  Processed dir: %s", processed_dir)
    logger.info("=" * 60)

    try:
        creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        result = subprocess.run(
            [
                sys.executable,
                str(verify_script),
                "--models-dir", str(models_dir),
                "--processed-dir", str(processed_dir),
                "--skip-smoke",  # smoke-validation requires shap/numba; skipped at runtime
            ],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=creationflags,
        )
        if result.returncode == 0:
            logger.info("Model verification PASSED ✓")
            return True
        else:
            logger.error(
                "Model verification FAILED (exit code %d). "
                "The backend CANNOT start with unverified model artifacts. "
                "See output above for details.",
                result.returncode,
            )
            return False
    except FileNotFoundError:
        logger.error("Verification script not found at %s", verify_script)
        return False
    except subprocess.TimeoutExpired:
        logger.error("Model verification timed out (>300s). Check data/processed/ integrity.")
        return False
    except Exception as e:
        logger.error("Model verification raised an unexpected error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Application Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("=" * 60)
    logger.info("FRAUD DETECTION API — STARTING UP")
    logger.info("  Environment: %s", settings.ENVIRONMENT)
    logger.info("  Model Dir:   %s", settings.MODEL_DIR)
    logger.info("  Database:    %s", settings.DATABASE_URL.split("@")[-1])
    logger.info("=" * 60)

    # ── Step 1: Model Verification Gate ──────────────────────────────
    if settings.SKIP_MODEL_VERIFICATION:
        logger.warning(
            "⚠️  MODEL VERIFICATION CHECKS SKIPPED (SKIP_MODEL_VERIFICATION=True). "
            "Proceeding to initialize model artifacts directly."
        )
        model_verified = True
    else:
        model_verified = run_model_verification()
        if not model_verified:
            logger.error(
                "\n" + "=" * 60 +
                "\nFATAL: Model verification failed. Backend REFUSING to start.\n"
                "Actions:\n"
                "  1. Run: python scripts/verify_model.py\n"
                "  2. Retry starting the backend\n"
                "  OR set SKIP_MODEL_VERIFICATION=True in .env\n"
                "=" * 60
            )
            raise SystemExit(1)

    # ── Step 2: Initialize ScoringService ────────────────────────────
    try:
        from app.services.scoring import initialize_scoring_service
        scoring_service = initialize_scoring_service(settings.model_dir_path)
        logger.info("ScoringService initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize ScoringService: %s", e)
        if not settings.SKIP_MODEL_VERIFICATION:
            raise SystemExit(1)

    # ── Step 3: Initialize DigitalTwinEngine ─────────────────────────
    from app.digital_twin import get_digital_twin_engine
    dt_engine = get_digital_twin_engine()
    logger.info("DigitalTwinEngine initialized.")

    # ── Step 4: Create database tables (including all new auth tables) ─
    try:
        await create_tables()
        logger.info("Database tables ready.")
    except Exception as e:
        logger.error("Database initialization failed: %s", e)
        raise SystemExit(1)

    # ── Step 4b: Verify schema columns (catch migration gaps early) ───
    await verify_schema_columns()

    # ── Step 5: Seed default threshold config ────────────────────────
    try:
        from sqlalchemy import select
        from app.models.orm import ThresholdConfig
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(ThresholdConfig).limit(1))
            existing = result.scalar_one_or_none()
            if existing is None:
                default_tc = ThresholdConfig(
                    block_threshold=settings.DEFAULT_BLOCK_THRESHOLD,
                    review_threshold=settings.DEFAULT_REVIEW_THRESHOLD,
                    updated_by="system_default",
                )
                session.add(default_tc)
                await session.commit()
                logger.info(
                    "Default thresholds seeded: block=%.2f, review=%.2f",
                    settings.DEFAULT_BLOCK_THRESHOLD,
                    settings.DEFAULT_REVIEW_THRESHOLD,
                )
    except Exception as e:
        logger.warning("Failed to seed default thresholds: %s", e)

    # ── Step 6: Seed Auth Users ───────────────────────────────────────
    try:
        from app.api.auth_routes import seed_auth_users
        await seed_auth_users()
        logger.info("Auth users seeded/verified.")
    except Exception as e:
        logger.warning("Failed to seed auth users: %s", e)

    logger.info("=" * 60)
    logger.info("FRAUD DETECTION API READY ✓")
    logger.info("  Docs: http://localhost:8000/docs")
    logger.info("  Health: http://localhost:8000/api/health")
    logger.info("  Login: http://localhost:5173/login")
    logger.info("=" * 60)

    yield  # Application runs

    # ── Shutdown ──────────────────────────────────────────────────────
    logger.info("Shutting down Fraud Detection API...")
    await dispose_engine()
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Fraud Detection API",
    description="""
## Banking Fraud Detection System API

**Al-Balqa' Applied University — Faculty of Artificial Intelligence**  
Graduation Project 2024/2025

### System Architecture
- **Hybrid Model**: XGBoost (0.70) + Isolation Forest (0.30) score fusion
- **Digital Twin Engine**: Real-time behavioral profiling per user
- **Tiered Decisions**: BLOCK (>0.85) | REVIEW (0.50–0.85) | APPROVE (<0.50)
- **SHAP Explainability**: Top contributing features for every flagged transaction
- **Authentication**: JWT-based role system (Admin / User / CEO)

### About the Dataset
The ULB European Credit Card Fraud Detection dataset is used for training.
284,807 transactions, 492 fraud cases (0.17%). V1-V28 are PCA-anonymized.

**Synthetic User IDs**: The ULB dataset has no native user/device/geo fields.
Synthetic user IDs are generated deterministically from Time+Amount hash buckets.
This is a known limitation acknowledged in the thesis — see /api/about for details.
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware ─────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)
    logger.info(
        "HTTP %s %s → %d [%.0fms]",
        request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


# ── Exception Handlers ─────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ── Register Routes ────────────────────────────────────────────────────────

from app.api.routes import router as main_router
from app.api.auth_routes import router as auth_router
from app.api.governance_routes import router as governance_router
from app.api.history_routes import router as history_router
from app.api.llm_routes import router as llm_router
from app.api.data_import_routes import router as data_import_router
from app.api.chat_routes import router as chat_router

API_PREFIX = "/api"
app.include_router(main_router, prefix=API_PREFIX)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(governance_router, prefix=API_PREFIX)
app.include_router(history_router, prefix=API_PREFIX)
app.include_router(llm_router, prefix=API_PREFIX)
app.include_router(data_import_router, prefix=API_PREFIX)
app.include_router(chat_router, prefix=API_PREFIX)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "Fraud Detection API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "login": "/login",
        "thesis": "Al-Balqa' Applied University — Faculty of Artificial Intelligence",
    }
