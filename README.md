# Trade Surveillance API (Sentinel backend)

FastAPI service for **trade surveillance**: REST API over **Supabase PostgreSQL**, optional **Supabase Storage** for ML artefacts, **Supabase JWT** validation for authenticated routes, and an **async AI investigation** path (Anthropic) for compliance memos.

The **Next.js** UI lives in a separate repo (`trade-surveillance-web`).

**Product & UX (v2 redesign):** see [`docs/SENTINEL_PRODUCT_SPEC_V2.md`](docs/SENTINEL_PRODUCT_SPEC_V2.md) — enums, RBAC, case-centric IA, API contracts, and implementation phases.

---

## Architecture overview

```
mock_data_script.py  →  Postgres (trades, dimensions, …)
        ↓
trade_surveillance.pipelines.feature_engineering  →  Supabase Storage (features.parquet)
        ↓
trade_surveillance.pipelines.anomaly_model       →  alerts + model_runs + Storage (model, medians)
        ↓
FastAPI /api/v1/*  ←  Next.js (JWT) — alerts, trades, notes, investigations, metrics, users
        ↓
POST /api/v1/investigations/run/{alert_id}  →  BackgroundTasks → investigate_trade() → investigations row
```

- **No AWS** in the current MVP path: storage and DB are Supabase-aligned.
- **Live streaming simulator** (`live_simulate.py`) was removed; bulk seeding remains via `mock_data_script.py`.

---

## Current backend state (development)

| Area | Status |
|------|--------|
| **REST API** | `/api/v1` trades, alerts, investigations, notes, model-runs, users, metrics/overview |
| **Auth** | `SUPABASE_JWT_SECRET` (+ optional `SUPABASE_JWT_ISSUER`); `get_current_user`; `require_compliance_lead` for sensitive user mutations |
| **Alerts** | Create/list/get/patch/delete; **COMPLIANCE_LEAD** only for terminal statuses `CLOSED` / `ESCALATED`; disposition required on close; server-stamped `reviewed_by` / `reviewed_at` |
| **Investigation notes** | `author_id` set server-side from JWT |
| **Agent** | `POST …/investigations/run/{alert_id}` queues `investigate_trade(alert_id)`; reads context from Postgres (`tools_db`); writes `investigations`; model via `ANTHROPIC_MODEL` |
| **Migrations** | `trade_surveillance/db/migrator.py` — idempotent DDL (e.g. `rule_violated` TEXT, `disposition` width, ML columns on alerts) |
| **Docker** | `pip install ".[agents]"` so Render image includes Anthropic/LangGraph stack |

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,all]"   # or ".[dev]" for API-only, ".[dev,agents]" for API + agent deps
cp .env.example .env
```

Fill `.env`: at minimum **`DATABASE_URL`**. For production auth: **`SUPABASE_JWT_SECRET`**. For investigations: **`ANTHROPIC_API_KEY`**. For pipelines + Storage: **`SUPABASE_URL`**, **`SUPABASE_SERVICE_ROLE_KEY`**, bucket keys — see `.env.example`.

```bash
uvicorn trade_surveillance.api.main:app --reload --port 8000
```

Health: `GET /health` and `GET /api/v1/health`.

---

## Demo data

One-shot synthetic load (defaults to large batch; tune with env vars):

```bash
OUTPUT_TARGET=database python mock_data_script.py
# NUM_TRADES=5000 OUTPUT_TARGET=database python mock_data_script.py
```

Ensure **`users`** rows exist with **`supabase_uid`** matching each Supabase Auth user so JWT login maps to app roles.

---

## ML pipelines (optional local / cron)

```bash
pip install -e ".[pipelines]"   # or ".[all]"
python -m trade_surveillance.pipelines.feature_engineering
python -m trade_surveillance.pipelines.anomaly_model
```

---

## Deploy (Render + Supabase)

1. **Supabase:** Postgres + Auth + (optional) Storage bucket for artefacts.  
2. **Render (or similar):** Build from repo **`Dockerfile`**; set `DATABASE_URL`, `ALLOWED_ORIGINS`, `SUPABASE_JWT_SECRET`, `ANTHROPIC_API_KEY`, and Storage vars if pipelines write to bucket.  
3. **Frontend:** Point `NEXT_PUBLIC_API_BASE_URL` at this service; allow the Vercel origin in `ALLOWED_ORIGINS`.

---

## Programmatic investigation (CLI / scripts)

Requires `pip install -e ".[agents]"` and env keys:

```python
from trade_surveillance import investigate_trade
result = investigate_trade("<alert-uuid>", auto_approve=True)
```

---

## Further reading

- **`trade-surveillance-mvp-stack.md`** — original stack choices (Supabase vs heavy AWS).  
- **`CLAUDE.md`** — commands and route table for agents / local dev.
