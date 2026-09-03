FROM python:3.11-slim

LABEL maintainer="Saleh Ghannmah <salehmax925@gmail.com>"
LABEL description="FraudShield AI — Fraud Detection Backend (FastAPI + XGBoost + Isolation Forest)"

WORKDIR /app

# ── System Dependencies ────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python Dependencies ────────────────────────────────────────────────────
# Install before copying source code to maximize Docker layer caching
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# ── Application Source ─────────────────────────────────────────────────────
# ml/ must be at /app/ml so it's importable from /app/backend
COPY ml /app/ml
COPY backend /app/backend
COPY scripts /app/scripts

# ── Model Artifacts ────────────────────────────────────────────────────────
# Models are small (~5MB total) and included in the image for fast cold starts
COPY models /app/models

# ── Processed Data (runtime requirements only) ─────────────────────────────
# test.parquet needed for simulation endpoint (~16MB)
# train.parquet and val.parquet are excluded (too large, not needed at runtime)
COPY data/processed/test.parquet /app/data/processed/test.parquet
COPY data/processed/scaler.joblib /app/data/processed/scaler.joblib
COPY data/processed/preprocessing_report.json /app/data/processed/preprocessing_report.json

# ── Python Path ────────────────────────────────────────────────────────────
# /app → ml/ importable as `import ml`
# /app/backend → `import app` importable
ENV PYTHONPATH=/app:/app/backend

# ── Production Defaults ────────────────────────────────────────────────────
# SKIP checksum subprocess — models are valid (verified during image build).
# The ScoringService still loads and validates models at runtime.
ENV SKIP_MODEL_VERIFICATION=True
ENV ENVIRONMENT=production
ENV DEBUG=False
# Hardcode model paths as Dockerfile defaults (prevents env var newline corruption)
ENV MODEL_DIR=/app/models
ENV PROCESSED_DATA_DIR=/app/data/processed

# ── Port ───────────────────────────────────────────────────────────────────
# Render injects $PORT automatically. Default to 8000 for local Docker runs.
EXPOSE 8000

WORKDIR /app/backend

# ── Healthcheck ────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# ── Start ──────────────────────────────────────────────────────────────────
CMD uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 1 \
    --timeout-keep-alive 75 \
    --log-level info
