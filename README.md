# Trade Surveillance API Backend

This repository is the backend/ML side of the MVP.  
Target architecture (from `trade-surveillance-mvp-stack.md`):

- Frontend: separate Next.js repo (`surveillance-web`)
- Backend: this Python repo (`surveillance-api`)
- Data/Auth/Storage: Supabase (Postgres, Auth, Storage)

The Streamlit dashboard is intentionally removed from this repo so the UI can live only in the Next.js app.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"     # optional: pytest + ruff
cp .env.example .env
```

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
python -m trade_surveillance.pipelines.feature_engineering
python -m trade_surveillance.pipelines.anomaly_model
python migrations.py create_tables
python migrations.py            # defaults to migrate: create_tables + migrations
python migrations.py migrate    # same as above
python migrations.py all        # alias for migrate
```

`migrate` always runs `create_tables()` from `trade_surveillance/models` first, then applies migration functions from `migrations.py`.

## Docker

```bash
cp .env.example .env
docker compose build
docker compose up backend
```

On startup, the API runs table creation + migrations automatically (controlled by `AUTO_MIGRATE_ON_STARTUP`, default `true`).

Programmatic investigation:

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
