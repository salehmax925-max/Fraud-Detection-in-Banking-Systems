FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2, pyarrow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy ml/ package from project root
COPY ../ml /app/ml

COPY . /app/backend
WORKDIR /app/backend

ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
