# Trade Surveillance API Backend

This repository is the backend/ML side of the MVP.  
Target architecture (from `trade-surveillance-mvp-stack.md`):

- Frontend: separate Next.js repo (`surveillance-web`)
- Backend: this Python repo (`surveillance-api`)
- Data/Auth/Storage: Supabase (Postgres, Auth, Storage)

The Streamlit dashboard is intentionally removed from this repo so the UI can live only in the Next.js app.

## Setup

Dependencies are declared in **`pyproject.toml`** (setuptools / PEP 621 — this repo does not use Poetry).

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,all]"   # full repo (API + pipelines + agents + pytest/ruff)
cp .env.example .env
```

Optional extras in `pyproject.toml`: **`pipelines`**, **`agents`**, **`all`**, **`dev`**. For a minimal API-only venv use `pip install -e ".[dev]"` (no pandas/S3/agents). Docker images use `pip install .` (API only).

## Current Backend Scope

| Path | Role |
|------|------|
| `trade_surveillance/` | Installable Python package |
| `trade_surveillance/pipelines/` | Feature engineering + anomaly model jobs |
| `trade_surveillance/agents/` | Investigation orchestration + memo generation |
| `tests/` | Pytest |

## Key Commands

```bash
uvicorn trade_surveillance.api.main:app --reload --port 8000
# Pipelines require: pip install -e ".[pipelines]" or ".[all]"
python -m trade_surveillance.pipelines.feature_engineering
python -m trade_surveillance.pipelines.anomaly_model
```

On API startup, `AUTO_MIGRATE_ON_STARTUP` (default `true`) runs `create_tables_and_migrate()` — see [`trade_surveillance/db/migrator.py`](trade_surveillance/db/migrator.py).

## Deploy (Phase 0) — Render + Vercel

1. **Supabase:** Create a project; copy a **pooler** `DATABASE_URL` — Session mode (5432) or Transaction mode (6543); the app configures psycopg for 6543 automatically (see [`.env.example`](.env.example)).
2. **This API on Render:** New **Web Service** → connect this repo → **Docker** using the repo-root [`Dockerfile`](Dockerfile) (or Native: build `pip install .`, start `uvicorn trade_surveillance.api.main:app --host 0.0.0.0 --port $PORT`). Optional: deploy from [`render.yaml`](render.yaml) as a [Render Blueprint](https://render.com/docs/blueprint-spec). Copy-paste backups of the same snippets live in [docs/phase-0-deploy-artifacts.md](docs/phase-0-deploy-artifacts.md).
3. **Environment variables on Render:** Set at least `DATABASE_URL`, `ALLOWED_ORIGINS` (include your Vercel production URL and `http://localhost:3000` for local UI). Optional: `ANTHROPIC_API_KEY`, `SUPABASE_*` for Storage (later phases).
4. **Health check:** Render should use path **`/health`** (root health endpoint).
5. **Frontend on Vercel:** In the Next.js repo, set `NEXT_PUBLIC_API_BASE_URL` to your Render service URL (no trailing slash). Ensure `ALLOWED_ORIGINS` on the API includes that Vercel origin so the browser is not blocked by CORS.

**Docker (optional local):** From repo root, after adding `Dockerfile` and `.dockerignore` (see [docs/phase-0-deploy-artifacts.md](docs/phase-0-deploy-artifacts.md)):

```bash
cp .env.example .env
docker build -t trade-surveillance-api .
docker run --rm -p 8000:8000 --env-file .env trade-surveillance-api
```

**Worker (later):** Phase 5 adds `python -m trade_surveillance.worker score-batch`. Until then, skip a second Render service (see commented worker block in the Blueprint snippet in [docs/phase-0-deploy-artifacts.md](docs/phase-0-deploy-artifacts.md)).

Programmatic investigation (requires `pip install -e ".[agents]"` or `.[all]`):

```python
from trade_surveillance import investigate_trade

result = investigate_trade("TRADE_ID_HERE", auto_approve=True)
print(result["verdict"], result.get("compliance_memo"))
```

## Next Steps (MVP Execution)

1. Build the Next.js frontend in a separate empty repo (`surveillance-web`) and keep it API-only (no direct DB access initially).
2. Add FastAPI endpoints in this repo for:
   - alert list
   - alert detail
   - disposition updates
   - investigation notes/audit trail
3. Move storage of queryable state to Supabase Postgres tables (`trades_raw`, `trade_features`, `alerts`, `investigations`, `investigation_notes`, `model_runs`).
4. Keep large artifacts (memo JSON, optional model files) in Supabase Storage.
5. Add scheduled backend jobs for feature/scoring runs, then have Next.js consume only backend API responses.
