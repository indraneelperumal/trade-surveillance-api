# Phase 0 — Deploy artifacts (reference copy)

The repo root now includes **`Dockerfile`**, **`.dockerignore`**, and **`render.yaml`** (Phase 0 implemented). This page keeps the same content as **backup / documentation** if those files are ever trimmed from git.

## `Dockerfile` (repo root)

```dockerfile
# Trade Surveillance API — production-style image (Render, Fly, etc.)
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY trade_surveillance ./trade_surveillance

RUN pip install --upgrade pip && pip install .

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn trade_surveillance.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

**Optional:** for LangGraph / `investigate_trade`, change the `pip install` line to `pip install ".[agents]"` (heavier image).

## `.dockerignore` (repo root)

```
.venv
__pycache__
*.py[cod]
.git
.gitignore
.pytest_cache
.ruff_cache
.env
.env.*
!.env.example
tests
docs
*.md
!README.md
```

## `render.yaml` (repo root, Render Blueprint)

```yaml
# https://render.com/docs/blueprint-spec
services:
  - type: web
    name: trade-surveillance-api
    runtime: docker
    dockerfilePath: ./Dockerfile
    plan: starter
    healthCheckPath: /health
    envVars:
      - key: APP_ENV
        value: production
      - key: AUTO_MIGRATE_ON_STARTUP
        value: "true"
      - key: ALLOWED_ORIGINS
        sync: false
      - key: DATABASE_URL
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
        optional: true
      - key: SUPABASE_URL
        sync: false
        optional: true
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
        optional: true
      - key: SUPABASE_STORAGE_BUCKET
        sync: false
        optional: true
```

Uncomment a **worker** service in Phase 5 when `trade_surveillance.worker` exists.

```yaml
  # - type: worker
  #   name: trade-surveillance-worker
  #   runtime: docker
  #   dockerfilePath: ./Dockerfile
  #   dockerCommand: python -m trade_surveillance.worker score-batch
```

## `.env.example` additions (also merged into repo root `.env.example`)

```bash
# --- Supabase Storage (Phase 3+ model artifacts / memos) ---
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=
# Private bucket for pkl / json exports (create in Supabase dashboard)
SUPABASE_STORAGE_BUCKET=trade-surveillance-artifacts

# --- Frontend (Vercel) — set on Vercel, not on this API ---
# NEXT_PUBLIC_API_BASE_URL=https://<your-render-service>.onrender.com
```

## `ALLOWED_ORIGINS` format

Comma-separated, no spaces unless inside quotes (FastAPI splits by comma). Example:

```bash
ALLOWED_ORIGINS=http://localhost:3000,https://your-app.vercel.app,https://*.vercel.app
```

Wildcard subdomains may not be supported by Starlette CORS — list each Vercel preview origin explicitly if needed.
