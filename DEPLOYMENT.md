# FraudShield AI — Deployment Guide

## Architecture

```
Internet
   │
   ▼
┌──────────────────────────────┐
│         VERCEL               │
│   React/Vite Frontend        │
│   fraudshield-ai.vercel.app  │
└──────────────────────────────┘
          │  HTTPS API calls
          │  (VITE_API_BASE_URL)
          ▼
┌──────────────────────────────────────────────────────┐
│              RENDER (Backend)                         │
│                                                      │
│  FastAPI + Uvicorn                                   │
│  XGBoost + Isolation Forest (scoring)                │
│  PandasDataAgent (live DB analytics via psycopg2)    │
│  Ollama + qwen3:8b (AI Chat — optional, fallback OK) │
└──────────────────────────────────────────────────────┘
          │  SSL/TLS
          ▼
┌──────────────────────────────┐
│         NEON                 │
│   PostgreSQL (managed)       │
│   Serverless + SSL           │
└──────────────────────────────┘
```

## Prerequisites

- GitHub account: `salehmax925-max`
- Neon account: [neon.tech](https://neon.tech) (free tier works)
- Render account: [render.com](https://render.com) (free or paid)
- Vercel account: [vercel.com](https://vercel.com) (free tier works)

---

## Step 1 — Neon PostgreSQL

1. Go to [neon.tech](https://neon.tech) → **New Project**
2. Name it `fraudshield`
3. Region: choose nearest (Europe, US East, etc.)
4. Once created, go to **Connection Details**
5. Copy the **Connection string** — it looks like:
   ```
   postgresql://user:password@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
6. You'll need two versions of this URL:
   - **DATABASE_URL** (asyncpg):
     ```
     postgresql+asyncpg://user:password@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
     ```
   - **DATABASE_SYNC_URL** (psycopg2):
     ```
     postgresql+psycopg2://user:password@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
     ```
   Just replace the `postgresql://` prefix with the respective driver prefix.

> [!NOTE]
> Schema is created automatically on first startup via SQLAlchemy `create_all()`.
> No manual migration needed.

---

## Step 2 — Backend on Render

### Create a Web Service

1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your GitHub repo: `salehmax925-max/Fraud-Detection-in-Banking-Systems`
3. Fill in:

| Setting | Value |
|---------|-------|
| **Name** | `fraudshield-backend` |
| **Region** | Same as Neon if possible |
| **Branch** | `main` |
| **Runtime** | **Docker** |
| **Dockerfile Path** | `./Dockerfile` |
| **Plan** | Starter ($7/mo) or higher |

### Environment Variables (set in Render dashboard)

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://...neon.tech/neondb?sslmode=require` |
| `DATABASE_SYNC_URL` | `postgresql+psycopg2://...neon.tech/neondb?sslmode=require` |
| `MODEL_DIR` | `/app/models` |
| `PROCESSED_DATA_DIR` | `/app/data/processed` |
| `SKIP_MODEL_VERIFICATION` | `True` |
| `CORS_ORIGINS` | `https://fraudshield-ai.vercel.app,http://localhost:5173` |
| `SECRET_KEY` | *(generate: `python -c "import secrets; print(secrets.token_hex(32))"`)* |
| `DEBUG` | `False` |
| `ENVIRONMENT` | `production` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` *(Ollama optional — chat falls back automatically)* |

> [!IMPORTANT]
> After Render deploys, copy the service URL: `https://fraudshield-backend.onrender.com`

### Verify Backend

```bash
curl https://fraudshield-backend.onrender.com/api/health
# Expected: {"status": "healthy", ...}
```

---

## Step 3 — Frontend on Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New → Project**
2. Import: `salehmax925-max/Fraud-Detection-in-Banking-Systems`
3. Configure:

| Setting | Value |
|---------|-------|
| **Framework Preset** | Vite |
| **Root Directory** | `.` (project root — vercel.json handles build) |
| **Build Command** | `cd frontend && npm install && npm run build` |
| **Output Directory** | `frontend/dist` |

4. **Environment Variables** (in Vercel project settings):

| Variable | Value |
|----------|-------|
| `VITE_API_BASE_URL` | `https://fraudshield-backend.onrender.com` |

5. Click **Deploy**

> [!NOTE]
> After deploy, update `CORS_ORIGINS` on Render to include your actual Vercel URL.

---

## Step 4 — Update CORS on Render

After getting your Vercel URL (e.g., `https://fraudshield-ai.vercel.app`):

1. Go to Render → `fraudshield-backend` → **Environment**
2. Update `CORS_ORIGINS`:
   ```
   https://fraudshield-ai.vercel.app,http://localhost:5173
   ```
3. Render auto-redeploys.

---

## Login Credentials

| Role | Username | Password |
|------|----------|----------|
| **Admin** | `Amin` | `2004` |
| CEO | `Hussain` | `hussain2024` |
| Analyst | `Analyst` | `analyst2024` |

---

## Ollama + qwen3:8b (Optional)

Ollama requires **5-8 GB RAM** which is not available on free/Starter hosting tiers.

**The application works fully without Ollama** — the AI Chat and LLM Explain features automatically fall back to:
- Built-in knowledge base (authoritative answers about the project)
- PandasDataAgent (live database analytics)
- Rule-based transaction explanations

To enable Ollama in production, you need a VPS with ≥8GB RAM:

```bash
# On a Linux VPS with enough RAM:
curl https://ollama.ai/install.sh | sh
ollama pull qwen3:8b
ollama serve --host 0.0.0.0

# Then set on Render:
OLLAMA_BASE_URL=http://your-vps-ip:11434
```

---

## How to Redeploy

### Backend (Render)
- Render auto-deploys when you push to `main` branch
- Manual: Render Dashboard → Service → **Manual Deploy**

### Frontend (Vercel)
- Vercel auto-deploys when you push to `main` branch
- Manual: Vercel Dashboard → Project → **Deployments → Redeploy**

---

## How to Inspect Logs

### Backend Logs
- Render Dashboard → Service → **Logs** tab (real-time streaming)

### Frontend Logs
- Browser DevTools → Console
- Vercel Dashboard → Deployment → **Functions** (for build logs)

---

## Environment Variables Reference

See [`.env.example`](.env.example) for all variables with descriptions.

**Never commit `.env` or any file with real passwords/secrets.**
