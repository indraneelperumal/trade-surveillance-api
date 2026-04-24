# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run feature engineering pipeline (reads S3, writes features.parquet)
python feature_engineering.py

# Run anomaly detection (reads features.parquet, writes anomalies.parquet + model artefacts)
python anomaly_model.py

# Investigate a single flagged trade (Phase 3 — LangGraph orchestrator)
python -c "
from agents import investigate_trade
result = investigate_trade('TRADE_ID_HERE', auto_approve=True)
print(result['verdict'], result['compliance_memo'])
"

# Run the Streamlit dashboard (Phase 4)
streamlit run dashboard.py

# Set up Glue catalog + Athena view (idempotent, run once per environment)
python step1_setup_glue_athena.py
```

AWS credentials are resolved via `AWS_PROFILE` in `.env`. The `.env` file must be present; the script raises `ValueError` immediately if `AWS_PROFILE` is missing.

## Pipeline Architecture

Data flows through four stages:

```
lambda_function.py          lambda_producer.py
(Kinesis producer)    →     (Kinesis → S3)         →   S3: raw/YYYY/MM/DD/*.json
  ↓ env: STREAM_NAME          ↓ env: BUCKET_NAME

step1_setup_glue_athena.py                          feature_engineering.py
Glue crawler → trade_surv.raw_trades       →        S3: features/features.parquet
Athena view  → trade_surv.raw_trades_v                         ↓
                                                    anomaly_model.py
                                                    S3: processed/anomalies.parquet
                                                    S3: model/isolation_forest.pkl
                                                    S3: model/medians.json
                                                               ↓
                                                    agents/orchestrator.py (Phase 3)
                                                    investigate_trade(trade_id)
                                                    → 4-node LangGraph StateGraph
                                                    → Claude Haiku compliance memo
                                                    S3: memos/{trade_id}.json
                                                               ↓
                                                    dashboard.py (Phase 4)
                                                    streamlit run dashboard.py
                                                    → reads anomalies.parquet + memos/
                                                    → live prices via yfinance
                                                    → triggers investigate_trade() on demand
```

**`lambda_function.py`** — Generates synthetic trades for 7 symbols (AAPL, MSFT, TSLA, AMZN, NVDA, GOOGL, META) with price random-walks, heavy-tailed volumes, and configurable off-hours/OTC ratios. Publishes N_TRADES records per invocation to the Kinesis stream named by `STREAM_NAME`. Key env vars: `STREAM_NAME`, `NUM_TRADES` (default 5), `EXT_HOURS_PCT` (default 0.10), `OTC_PCT` (default 0.15).

**`lambda_producer.py`** — Kinesis-triggered; decodes base64 records and writes newline-delimited JSON to S3 at `raw/{YYYY}/{MM}/{DD}/{HHMMSS-microseconds}.json`. Env vars: `BUCKET_NAME`, `RAW_PREFIX` (default `raw/`).

**`step1_setup_glue_athena.py`** — Idempotent setup script. Creates Glue database `trade_surv`, runs crawler `raw-trades-crawler` against `s3://trade-surveillance-bucket/raw/`, copies the crawler-managed `raw` table to the canonical `raw_trades` table, creates Athena workgroup `trade-surveillance-wg` (results → `s3://trade-surveillance-bucket/athena-results/`), and creates view `trade_surv.raw_trades_v`. Requires IAM role `AWSGlueServiceRole-trade-surv` to exist before running (creation commands are in the script's docstring).

**`feature_engineering.py`** — Downloads all 30,424+ NDJSON files from `raw/` using 32 parallel threads, engineers 12 features, and writes `features/features.parquet` (Snappy-compressed) using a write-to-temp-key + `copy_object` pattern for safe overwrites.

**`anomaly_model.py`** — Reads `features/features.parquet`, injects 50 labelled synthetic anomalies for recall validation, trains `IsolationForest(n_estimators=200, contamination=0.08, random_state=42)` on the full frame, scores every trade, runs SHAP TreeExplainer on flagged trades only, classifies anomaly type by rule, validates synthetic recall (target ≥ 80%), removes synthetics, and writes three artefacts to S3. Achieved: 88% synthetic recall, ~12,100 anomalies flagged (8% of 152,010 trades).

**`agents/`** — Phase 3 LangGraph orchestrator. Entry point: `from agents import investigate_trade`. Requires `ANTHROPIC_API_KEY` in `.env` in addition to `AWS_PROFILE`.

**`dashboard.py`** — Phase 4 Streamlit UI. Single-file, ~650 lines. Reads `processed/anomalies.parquet` and `memos/` from S3 on startup (cached via `@st.cache_data`), fetches live prices from yfinance, and calls `investigate_trade()` on demand from Tab 2. Session 1 shipped Tab 1 (Overview) fully; Tabs 2–4 are stubs pending future sessions.

## AWS Resources

| Resource | Name |
|---|---|
| S3 bucket | `trade-surveillance-bucket` |
| Region | `us-east-2` |
| Glue database | `trade_surv` |
| Glue crawler | `raw-trades-crawler` |
| Glue table (canonical) | `trade_surv.raw_trades` |
| Glue table (crawler-managed) | `trade_surv.raw` |
| Athena view | `trade_surv.raw_trades_v` |
| Athena workgroup | `trade-surveillance-wg` |
| IAM account ID | `052893174124` |

## S3 Artefact Map

| S3 key | Written by | Content |
|---|---|---|
| `raw/YYYY/MM/DD/*.json` | `lambda_producer.py` | NDJSON trade records |
| `features/features.parquet` | `feature_engineering.py` | 152,010 rows × 32 cols, Snappy |
| `processed/anomalies.parquet` | `anomaly_model.py` | 152,010 rows × 40 cols, Snappy |
| `model/isolation_forest.pkl` | `anomaly_model.py` | Trained IsolationForest (~2.4 MB) |
| `model/medians.json` | `anomaly_model.py` | Per-feature medians for inference |
| `memos/{trade_id}.json` | `agents/orchestrator.py` | Structured compliance memo JSON |
| `athena-results/` | Athena | Query result CSVs |

## Raw Data Schema

18 fields per record. Key details:
- `timestamp`: ISO-8601 with UTC offset (`+00:00`) — use `from_iso8601_timestamp()` in Athena, `pd.to_datetime(..., utc=True)` in pandas
- `side`: always `"Buy"` or `"Sell"` from the generator
- `exchange`: `NASDAQ`, `NYSE`, `BATS`, `ARCA`, `DARK`, `ATS01`, or `OTC`
- S3 partitioning is non-Hive (`YYYY/MM/DD/`) — Glue names the partition columns `partition_0`, `partition_1`, `partition_2`

## Feature Engineering Details

12 features added by `feature_engineering.py` (all float64 unless noted):

| Feature | Grouping |
|---|---|
| `spread`, `mid_price`, `relative_spread`, `depth_imbalance` | row-level |
| `z_score_price`, `z_score_volume` | symbol × date, ddof=1 |
| `trader_volume_share` | denominator = symbol × date total volume |
| `is_off_hours` (bool) | US/Eastern timezone, NYSE hours 09:30–16:00 |
| `is_otc` (bool) | row-level |
| `inter_arrival_time`, `return_vs_prev` | symbol, sorted by timestamp |
| `trader_buy_sell_ratio` | trader_id × date; sell-only traders → 0.0 |

Output schema: 18 original columns + `date` + 12 features = 32 columns.

## Anomaly Model Details

`anomaly_model.py` adds 8 columns to produce the 40-column `anomalies.parquet`:

| Column | dtype | Notes |
|---|---|---|
| `anomaly_score` | float64 | Raw `decision_function` output; **negative = more anomalous** |
| `is_anomaly` | bool | True if model flagged the row (8% of trades) |
| `anomaly_rank` | float64 | Rank 1 = most anomalous, 152,010 = most normal; re-ranked on real trades only |
| `top_3_shap_features` | str / None | JSON list of top-3 `[feature, shap_value]` pairs; flagged rows only |
| `top_shap_feature` | str / None | Strongest SHAP feature name; flagged rows only |
| `anomaly_type` | str / None | Rule-based: `fat_finger`, `volume_spike`, `off_hours`, `spoofing`, `wash_trade`, `multi_flag`, `unknown` |
| `injected` | bool | Always False in output (synthetics removed before save) |
| `injected_type` | str / None | Always None in output |

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

To score new trades against the saved model: load `model/medians.json` for NaN-filling, `model/isolation_forest.pkl` for inference. Apply the same bool→int cast for `is_off_hours`/`is_otc` before calling `decision_function`.

## Agent Orchestrator Details (Phase 3)

`agents/` contains a 4-node LangGraph StateGraph (`agents/orchestrator.py`). Call via `investigate_trade(trade_id, auto_approve=False)`.

### Graph nodes

| Node | Purpose |
|---|---|
| `trade_context_node` | Loads anomaly record + trader history; computes trader stats |
| `market_context_node` | Loads ±60-min symbol window; computes market context |
| `regulatory_screen_node` | Applies 5 rule conditions; derives severity |
| `human_review_node` | Prints findings + calls `interrupt()` for HIGH severity when `auto_approve=False` |
| `compliance_memo_node` | Calls Claude Haiku; generates structured JSON memo; uploads to S3 |

### Severity and verdict logic

| Severity | Condition | Verdict override |
|---|---|---|
| `HIGH` | FAT_FINGER or VOLUME_SPIKE in matched, or ≥2 rules | `ESCALATE` (if confidence=HIGH) / `MONITOR` |
| `MEDIUM` | SPOOFING or WASH_TRADE | `MONITOR` |
| `LOW` | OFF_HOURS only | `DISMISS` |
| `NONE` | No rules matched | `DISMISS` |

### Caching

`_load_anomalies_df(profile)` and `_load_features_df(profile)` use `@functools.lru_cache` — both 40 MB+ parquet files are downloaded once per session and cached in memory. Callers (`load_anomaly_record`, `load_trader_history`, `load_market_window`) read from the cache.

### Regulatory rules

| Rule | Condition |
|---|---|
| `FAT_FINGER` | `z_score_price > 4` |
| `VOLUME_SPIKE` | `z_score_volume > 4` |
| `OFF_HOURS` | `is_off_hours == True` |
| `SPOOFING` | `abs(depth_imbalance) > 0.8` |
| `WASH_TRADE` | `trader_buy_sell_ratio > 0.9` AND `z_score_volume > 2` |

### Memo schema (Claude output)

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

## Athena Query Notes

- Always filter on `dt` to prune partitions: `WHERE dt = DATE '2024-01-15'`
- `timestamp` is a reserved word in Athena/Presto — always double-quote it: `"timestamp"`
- Numeric columns in the raw table may be inferred as strings by the Glue JSON classifier; the `raw_trades_v` view explicitly casts them to `DOUBLE`/`BIGINT`

## Dashboard Details (Phase 4)

`dashboard.py` is a single-file Streamlit app. `st.set_page_config()` must always be the **first** Streamlit call in `main()`.

### S3 reads

Dashboard uses `boto3.client("s3")` (no `profile_name` kwarg) — it inherits `AWS_PROFILE` from the environment via `load_dotenv()` at module top. Do not add `profile_name`; it would break when running under IAM roles or CI.

### Caching strategy

| Function | TTL | Notes |
|---|---|---|
| `load_anomalies()` | 300 s | Full 40-col parquet, ~40 MB |
| `load_memos_list()` | 300 s | S3 key listing only; call `.clear()` after new investigation |
| `load_memo(trade_id)` | 300 s | Single JSON per trade |
| `get_live_prices(symbols)` | 60 s | `symbols` must be a **tuple** (hashable); `.clear()` on 60s timer |
| `get_stock_history(symbol, period)` | 300 s | yfinance OHLCV |

### Color system

All colors are module-level constants (`BG_PRIMARY`, `BG_CARD`, `BG_CARD2`, `BORDER`, `GREEN`, `RED`, `YELLOW`, `BLUE`, `TEXT`, `TEXT_DIM`, `PURPLE`). Never use 8-character hex (`#RRGGBBAA`) — use the `hex_to_rgba(hex, alpha)` helper for transparency. All Plotly figures share `PLOTLY_LAYOUT = dict(paper_bgcolor=BG_PRIMARY, plot_bgcolor=BG_CARD, font_color=TEXT, ...)`.

### Key helpers

- `hex_to_rgba(hex_color, alpha) -> str` — converts `#RRGGBB` to `rgba(r,g,b,a)`
- `get_severity(anomaly_type) -> str` — maps type string to `HIGH/MEDIUM/LOW/NONE`
- `run_investigation(trade_id) -> dict` — wraps `investigate_trade(auto_approve=True)`; returns `{"verdict":"ERROR",...}` on any exception

### Session state keys

Initialised in `main()` before any tab renders:

| Key | Type | Purpose |
|---|---|---|
| `verdicts` | `dict` | `{trade_id: verdict}` for investigated trades |
| `memos` | `dict` | `{trade_id: memo_dict}` cache for inline rendering |
| `open_memos` | `set` | Trade IDs whose memo card is currently expanded |
| `selected_symbol` | `str` | Symbol filter shared across tabs |
| `investigated_today` | `set` | Trade IDs investigated in this session |
| `last_ticker_refresh` | `float` | `time.time()` of last yfinance refresh |

### Tab build status

| Tab | Label | Status |
|---|---|---|
| 1 | 📊 Overview | Complete — progress card, KPIs, charts, escalation feed |
| 2 | 🚨 Flagged Trades | Stub — to be built Session 2 |
| 3 | 📋 Reports | Stub — to be built Session 3 |
| 4 | 📈 Market Context | Stub — to be built Session 4 |
