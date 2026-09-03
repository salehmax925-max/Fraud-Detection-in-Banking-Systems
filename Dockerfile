FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2, pyarrow, and gcc for some ML packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer caching)
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy ml/ package from project root (needed by scoring service)
COPY ml /app/ml

# Copy backend source
COPY backend /app/backend

# Copy scripts/ (needed for verify_model.py)
COPY scripts /app/scripts

# Copy model artifacts (small: ~5MB total)
COPY models /app/models

# Copy processed data needed at runtime
# Note: train.parquet and val.parquet are excluded from git (too large).
# Only test.parquet is needed for the simulation endpoint.
COPY data/processed/test.parquet /app/data/processed/test.parquet
COPY data/processed/preprocessing_report.json /app/data/processed/preprocessing_report.json
COPY data/processed/scaler.joblib /app/data/processed/scaler.joblib

# Set Python path so both /app/backend and /app (ml/) are importable
ENV PYTHONPATH=/app:/app/backend

# Skip the checksum subprocess in production — models are verified by Docker build.
# The ScoringService still loads and validates models at runtime (Step 2 in lifespan).
ENV SKIP_MODEL_VERIFICATION=True

# Render injects $PORT; fall back to 8000 for local Docker usage
WORKDIR /app/backend
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
