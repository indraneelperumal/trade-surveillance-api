# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install API + dev tools (default)
pip install -e ".[dev]"

# Install with ML pipelines
pip install -e ".[dev,pipelines]"

# Install everything (API + pipelines + agents)
pip install -e ".[dev,all]"

# Run the API locally
uvicorn trade_surveillance.api.main:app --reload --port 8000

# Run with Docker
docker compose up --build

# Run database migrations manually
python migrations.py migrate

# Seed the database with synthetic trades (default: 200k trades, database mode)
python mock_data_script.py
# Or with env overrides:
NUM_TRADES=5000 OUTPUT_TARGET=database python mock_data_script.py

# Run feature engineering pipeline (reads S3, writes features.parquet) — needs .[pipelines] or .[all]
python -m trade_surveillance.pipelines.feature_engineering

# Run anomaly detection (reads features.parquet, writes anomalies.parquet + model artefacts)
python -m trade_surveillance.pipelines.anomaly_model

# Investigate a single flagged trade (Phase 3 — LangGraph orchestrator) — needs .[agents] or .[all]
python -c "
from trade_surveillance import investigate_trade
result = investigate_trade('TRADE_ID_HERE', auto_approve=True)
print(result['verdict'], result['compliance_memo'])
"

# Lint
ruff check .
```

## Architecture Overview

This is a **FastAPI + PostgreSQL backend** (primary) with an optional ML pipeline layer (secondary, batch).

```
mock_data_script.py
(Synthetic trade generator)
  ↓ OUTPUT_TARGET=database
PostgreSQL (Supabase)
  trades, alerts, investigations,
  investigation_notes, model_runs, users,
  traders, clients, counterparties, instruments
  ↓
FastAPI REST API  (trade_surveillance/api/)
  /api/v1/trades
  /api/v1/alerts
  /api/v1/investigations
  /api/v1/investigation-notes
  /api/v1/model-runs
  /api/v1/users
  /api/v1/metrics/overview
  ↓
Next.js frontend (separate repo: surveillance-web)

─── Optional ML batch pipeline (runs independently) ────────────────────
mock_data_script.py (OUTPUT_TARGET=kinesis) → Kinesis → S3: raw/YYYY/MM/DD/*.json
step1_setup_glue_athena.py                  → Glue/Athena query layer
trade_surveillance.pipelines.feature_engineering → S3: features/features.parquet
trade_surveillance.pipelines.anomaly_model       → S3: processed/anomalies.parquet
trade_surveillance.agents.orchestrator           → Claude Haiku compliance memo
```

## Environment Variables

Required:
- `DATABASE_URL` — PostgreSQL connection string (e.g. `postgresql+psycopg://user:pass@host/db`)

Optional:
- `APP_ENV` — `development` (default) or `production`
- `ALLOWED_ORIGINS` — comma-separated CORS origins (default: `http://localhost:3000`)
- `AUTO_MIGRATE_ON_STARTUP` — `true` (default) runs `create_tables_and_migrate()` on startup
- `AWS_PROFILE` — required for ML pipeline and agent jobs only
- `ANTHROPIC_API_KEY` — required for the LangGraph agent orchestrator only
- `TSP_S3_BUCKET`, `TSP_RAW_PREFIX`, `TSP_FEATURES_KEY`, `TSP_ANOMALIES_KEY`, `TSP_MODEL_KEY`, `TSP_MEDIANS_KEY`, `TSP_MEMOS_PREFIX` — S3 layout overrides (ML pipeline only)

Mock data script env vars:
- `NUM_TRADES` — number of trades to generate (default: 200000)
- `OUTPUT_TARGET` — `database` (default) or `kinesis`
- `DB_BATCH_SIZE` — insert batch size (default: 5000)
- `EXT_HOURS_PCT` — fraction of off-hours trades (default: 0.10)
- `OTC_PCT` — fraction of OTC trades (default: 0.15)
- `ANOMALY_RATE` — overall anomaly injection rate (default: 0.12)

## REST API

Base path: `/api/v1`. All list endpoints return paginated responses: `{ items, total, offset, limit }`. All errors return: `{ error: { code, message, details } }`.

### Routes

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Root health check |
| GET | `/api/v1/health` | Versioned health check |
| POST/GET | `/api/v1/trades` | Create / list trades (`?symbol=`, `?offset=`, `?limit=`) |
| GET/PATCH/DELETE | `/api/v1/trades/{id}` | Get / update / delete trade |
| POST/GET | `/api/v1/alerts` | Create / list alerts (`?status=`, `?severity=`, `?anomalyType=`, `?symbol=`) |
| GET/PATCH/DELETE | `/api/v1/alerts/{id}` | Get / update / delete alert |
| POST/GET | `/api/v1/investigations` | Create / list investigations (`?alert_id=`) |
| GET/PATCH/DELETE | `/api/v1/investigations/{id}` | Get / update / delete investigation |
| POST/GET | `/api/v1/investigation-notes` | Create / list notes (`?alert_id=`, `?investigation_id=`) |
| GET/PATCH/DELETE | `/api/v1/investigation-notes/{id}` | Get / update / delete note |
| POST/GET | `/api/v1/model-runs` | Create / list model runs |
| GET/PATCH/DELETE | `/api/v1/model-runs/{id}` | Get / update / delete model run |
| POST/GET | `/api/v1/users` | Create / list users |
| GET/PATCH/DELETE | `/api/v1/users/{id}` | Get / update / delete user |
| GET | `/api/v1/metrics/overview` | Dashboard KPI aggregates |

### Metrics overview response shape

```json
{
  "total_alerts": 0,
  "total_trades": 0,
  "alerts_by_status": {},
  "alerts_by_severity": {},
  "alerts_by_anomaly_type": {},
  "open_alerts_by_severity": {},
  "open_high_severity_count": 0,
  "top_symbols_by_alerts": [{ "symbol": "TSLA", "count": 0 }]
}
```

## Database Schema

PostgreSQL via SQLAlchemy 2.0 + Pydantic. Tables auto-created on startup when `AUTO_MIGRATE_ON_STARTUP=true`. Manual migrations live in `trade_surveillance/db/migrator.py:run_migrations()`.

### Core tables

**trades** — one row per trade event. Primary key: `trade_id` (UUID). FK references: `instruments.symbol`, `traders.trader_id`, `clients.client_id`, `counterparties.counterparty_id`. Contains all raw fields + pre-computed feature columns.

**alerts** — one alert per flagged trade (unique on `trade_id`). Fields: `anomaly_score`, `anomaly_rank`, `anomaly_type`, `top_shap_feature`, `top_3_shap_features` (JSONB), `severity` (`HIGH|MEDIUM|LOW|NONE`), `status` (`OPEN|IN_PROGRESS|CLOSED`), `disposition`, `assigned_to`, `reviewed_by`, `reviewed_at`, `notes`.

**investigations** — AI-generated or manual investigation for an alert. Fields: `verdict`, `confidence`, `rule_violated`, `summary`, `evidence_points` (JSONB), `recommended_action`, `data_gaps`, `memo_json` (JSONB), `memo_storage_key`, `is_auto`, `initiated_by`.

**investigation_notes** — chronological audit trail for an alert/investigation. Linked via `alert_id` and optional `investigation_id`.

**model_runs** — tracks batch pipeline executions (status, metrics, artefact paths, run parameters).

**users** — app-level user records. `role`: `ANALYST` or `COMPLIANCE_LEAD`. `supabase_uid` links to Supabase Auth; authentication is handled externally, not by this API.

**instruments** — 14 symbols: AAPL, MSFT, TSLA, AMZN, NVDA, GOOGL, META, JPM, GS, BAC, XOM, JNJ, QQQ, SPY. Stores ISIN, CUSIP, sector, industry, asset_class, base_price, ann_vol, avg_spread_bps, avg_daily_vol.

**traders** — 200 synthetic traders (TR0001–TR0200). Fields: desk, book, region, type, risk_limit_usd, preferred_symbols, off_hours_tendency, avg_order_size, buy_side_bias.

**clients** — 500 synthetic clients (CL00001–CL00500). Fields: client_type, client_lei, client_domicile, client_mifid_category, aum_tier.

**counterparties** — 8 fixed counterparties (Goldman Sachs, Morgan Stanley, JP Morgan, Citadel Securities, Virtu Financial, Two Sigma, Jane Street, Interactive Brokers).

## Mock Data Script (`mock_data_script.py`)

Generates enterprise-grade synthetic trades and writes them to the database (default) or Kinesis.

- **14 instruments** with GBM price walks, realistic spreads, and sector metadata
- **200 trader profiles** with desk, region, type, buy_side_bias, off_hours_tendency
- **500 client profiles** with MiFID category, LEI, AUM tier, domicile
- **Anomaly seeding** at 12% base rate with 6 types:

| Type | Seeding mechanism |
|---|---|
| `fat_finger` | GBM shock multiplier (7–14% price jump) |
| `volume_spike` | LARGE/BLOCK tier + 2.2–4.8× multiplier |
| `off_hours` | Forced off-hours timestamp |
| `spoofing` | spoof_bias > 0.95 → heavy bid/ask size skew |
| `wash_trade` | buy_side_bias → 0.92–0.99 + LARGE/BLOCK volume |
| `multi_flag` | Combines fat_finger + off_hours + wash_trade signals |

`seeded_anomaly_type` field is generated per trade but not written to the `trades` table (QA/recall use only).

## ML Pipeline (Optional Batch Layer)

### Feature Engineering (`trade_surveillance/pipelines/feature_engineering.py`)

Reads NDJSON files from S3 `raw/`, engineers 12 features, writes `features/features.parquet` (Snappy, 32 cols). Uses 32 parallel threads + write-to-temp-key + `copy_object` pattern for safe overwrites.

12 engineered features (all float64 unless noted):

| Feature | Grouping |
|---|---|
| `spread`, `mid_price`, `relative_spread`, `depth_imbalance` | row-level |
| `z_score_price`, `z_score_volume` | symbol × date, ddof=1 |
| `trader_volume_share` | symbol × date total volume |
| `is_off_hours` (bool) | US/Eastern, NYSE hours 09:30–16:00 |
| `is_otc` (bool) | row-level |
| `inter_arrival_time`, `return_vs_prev` | symbol, sorted by timestamp |
| `trader_buy_sell_ratio` | trader_id × date; sell-only → 0.0 |

### Anomaly Model (`trade_surveillance/pipelines/anomaly_model.py`)

Reads `features/features.parquet`, trains `IsolationForest(n_estimators=200, contamination=0.08, random_state=42)`, runs SHAP TreeExplainer on flagged trades, classifies by rule. Achieved: 88% synthetic recall, ~12,100 anomalies flagged (8% of 152,010 trades).

Writes three artefacts to S3: `processed/anomalies.parquet`, `model/isolation_forest.pkl`, `model/medians.json`.

Anomaly type rules (applied to flagged trades only):

| Type | Condition |
|---|---|
| `fat_finger` | `z_score_price > 4` |
| `volume_spike` | `z_score_volume > 4` |
| `off_hours` | `is_off_hours == True` |
| `spoofing` | `abs(depth_imbalance) > 0.8` |
| `wash_trade` | `trader_buy_sell_ratio > 0.9` AND `z_score_volume > 2` |
| `multi_flag` | more than one condition matches |
| `unknown` | flagged but no condition matches |

### Agent Orchestrator (`trade_surveillance/agents/`)

4-node LangGraph StateGraph. Entry: `from trade_surveillance import investigate_trade`. Requires `ANTHROPIC_API_KEY` + `AWS_PROFILE` in `.env`.

Nodes: `trade_context_node` → `market_context_node` → `regulatory_screen_node` → `human_review_node` → `compliance_memo_node`.

Memo schema (Claude Haiku output):
```json
{
  "summary": "...",
  "evidence_points": ["...", "..."],
  "rule_violated": "RULE_NAME or NONE",
  "verdict": "ESCALATE | MONITOR | DISMISS",
  "confidence": "HIGH | MEDIUM | LOW",
  "recommended_action": "...",
  "data_gaps": "..."
}
```

## AWS Resources (ML Pipeline Only)

| Resource | Name |
|---|---|
| S3 bucket | `trade-surveillance-bucket` |
| Region | `us-east-2` |
| Glue database | `trade_surv` |
| Athena workgroup | `trade-surveillance-wg` |
| IAM account ID | `052893174124` |

## Frontend Guidance

- Frontend lives in a **separate Next.js repo** (`surveillance-web`). Keep it out of this repo.
- Next.js App Router + TypeScript + TanStack Query + shadcn/ui.
- Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` in the frontend `.env`.
- Frontend consumes backend APIs only — never direct DB access.
- All list endpoints are paginated. All errors use the normalized envelope: `{ error: { code, message, details } }`.
- Authentication is handled by Supabase Auth. This API trusts the caller; add middleware for token validation when ready.
- See `frontend-build-context.md` for full frontend IA, UX notes, and backlog.

## Product Goals (MVP)

1. Compliance analysts can triage flagged trades from an alert queue.
2. Core workflow: view alert → inspect trade → add notes → set disposition.
3. Fully auditable trail: every change is timestamped with actor.
4. Model run transparency: analysts see what the model flagged and why.
5. Target: analyst moves from alert to disposition in < 2 minutes.
