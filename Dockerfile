FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2, pyarrow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer caching)
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy ml/ package from project root
COPY ml /app/ml

# Copy backend source
COPY backend /app/backend

# Copy models and processed data (needed at runtime)
COPY models /app/models
COPY data/processed/test.parquet /app/data/processed/test.parquet
COPY data/processed/preprocessing_report.json /app/data/processed/preprocessing_report.json

# Set Python path so both /app/backend and /app (ml/) are importable
ENV PYTHONPATH=/app:/app/backend

WORKDIR /app/backend

EXPOSE 8000

# Render uses $PORT env var
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
