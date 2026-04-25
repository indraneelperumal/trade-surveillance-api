# Trade surveillance platform (demo)

End-to-end sketch: raw trades in **S3** → **feature engineering** → **Isolation Forest** scoring + SHAP → **LangGraph** investigation with an LLM memo → **Streamlit** dashboard.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"     # optional: pytest + ruff
cp .env.example .env        # then fill AWS_PROFILE and ANTHROPIC_API_KEY
```

## Layout

| Path | Role |
|------|------|
| `trade_surveillance/` | Installable Python package |
| `trade_surveillance/config.py` | S3 bucket and key paths (`TSP_*` env vars) |
| `trade_surveillance/aws/` | Shared S3 helpers |
| `trade_surveillance/pipelines/` | Batch: features + anomaly model |
| `trade_surveillance/agents/` | LangGraph orchestrator + tools |
| `apps/dashboard.py` | Streamlit UI |
| `tests/` | Pytest |

## Commands

```bash
python -m trade_surveillance.pipelines.feature_engineering
python -m trade_surveillance.pipelines.anomaly_model
streamlit run apps/dashboard.py
```

Programmatic investigation:

```python
from trade_surveillance import investigate_trade

result = investigate_trade("TRADE_ID_HERE", auto_approve=True)
print(result["verdict"], result.get("compliance_memo"))
```

See `CLAUDE.md` for AWS resource names and data semantics.
