"""
tools_db.py — PostgreSQL-backed data loading for the compliance agent.

Replaces the deprecated tools.py which read from AWS S3.
All data comes from Supabase (PostgreSQL) via the shared SQLAlchemy engine.

Design note — Showstopper 1 fix:
  The regulatory_screen_node requires engineered ML features (z_score_price,
  z_score_volume, depth_imbalance, trader_buy_sell_ratio, etc.) to run its
  rule match.  These features are NOT columns on the trades table; they are
  computed by the anomaly pipeline and stored in alerts.model_features (JSONB).
  load_alert_with_trade() merges that JSONB dict into the returned record so
  every downstream node sees them directly on raw_trade.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import text

from trade_surveillance.db.migrator import get_engine


# ── Feature names that live in alerts.model_features ─────────────────────────
# These must NOT be confused with native trade-table columns.
ML_FEATURE_COLS = (
    "z_score_price",
    "z_score_volume",
    "depth_imbalance",
    "trader_volume_share",
    "trader_buy_sell_ratio",
    "inter_arrival_time",
    "return_vs_prev",
    # The following also appear on the trades table; the native value wins via
    # setdefault() below, which is intentional.
    "spread",
    "mid_price",
    "relative_spread",
    "is_off_hours",
    "is_otc",
)


def load_alert_with_trade(alert_id: str) -> dict:
    """
    Load the alert row and its linked trade row from PostgreSQL.

    Merges alert.model_features (the 12 engineered ML features computed by the
    anomaly pipeline) into the returned dict.  This makes z_score_price,
    depth_imbalance, trader_buy_sell_ratio, etc. available directly on
    raw_trade — which is what regulatory_screen_node reads.

    Raises ValueError if the alert does not exist.
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT
                    -- Alert fields
                    a.id               AS alert_id,
                    a.anomaly_score,
                    a.anomaly_rank,
                    a.anomaly_type,
                    a.top_shap_feature,
                    a.top_3_shap_features,
                    a.model_features,
                    a.severity         AS alert_severity,
                    a.status           AS alert_status,
                    -- Trade identifiers
                    t.trade_id,
                    t.symbol,
                    t.timestamp,
                    t.exchange,
                    t.side,
                    t.price,
                    t.volume,
                    t.trade_value,
                    -- Trader context
                    t.trader_id,
                    t.trader_desk,
                    t.trader_region,
                    t.trader_type,
                    t.risk_limit_usd,
                    -- Client context
                    t.client_id,
                    t.client_type,
                    t.client_mifid_category,
                    t.aum_tier,
                    -- Counterparty
                    t.counterparty_name,
                    t.counterparty_type,
                    -- Trade attributes
                    t.is_off_hours,
                    t.is_otc,
                    t.is_block_trade,
                    t.algo_used,
                    t.algo_strategy,
                    t.order_type,
                    -- Market microstructure (native trade columns)
                    t.bid_price,
                    t.ask_price,
                    t.bid_size,
                    t.ask_size,
                    t.spread,
                    t.relative_spread,
                    t.mid_price,
                    t.spread_bps,
                    t.price_vs_nbbo_bps,
                    t.adv_pct,
                    -- Instrument metadata
                    t.sector,
                    t.asset_class,
                    t.currency
                FROM alerts a
                JOIN trades t ON t.trade_id = a.trade_id
                WHERE a.id = :alert_id::uuid
            """),
            {"alert_id": alert_id},
        ).mappings().one_or_none()

    if row is None:
        raise ValueError(
            f"Alert {alert_id!r} not found. "
            "Ensure the ML pipeline has run and alerts have been written to the database."
        )

    record: dict = dict(row)

    # ── Merge engineered ML features from JSONB ───────────────────────────────
    # model_features contains z_score_price, z_score_volume, depth_imbalance,
    # trader_buy_sell_ratio, etc.  We use setdefault so native trade columns
    # (is_off_hours, spread, mid_price, relative_spread) are never overwritten.
    raw_features: Optional[dict] = record.pop("model_features", None)
    if raw_features:
        if isinstance(raw_features, str):
            try:
                raw_features = json.loads(raw_features)
            except (json.JSONDecodeError, TypeError):
                raw_features = {}
        if isinstance(raw_features, dict):
            for k, v in raw_features.items():
                record.setdefault(k, v)

    # ── Normalise types for downstream nodes ──────────────────────────────────
    record["trade_id"] = str(record["trade_id"])
    record["alert_id"] = str(record["alert_id"])
    if record.get("timestamp") is not None:
        record["timestamp"] = str(record["timestamp"])

    return record


def load_trader_history(
    trader_id: str,
    symbol: Optional[str] = None,
    limit: int = 30,
) -> pd.DataFrame:
    """
    Load the most-recent `limit` trades for a given trader.

    Pass `symbol` to restrict to same-instrument history, which tightens the
    statistical baseline for buy/sell ratio and volume comparison.
    """
    base_q = """
        SELECT
            trade_id,
            symbol,
            timestamp,
            side,
            price,
            volume,
            is_off_hours,
            is_otc,
            trader_id
        FROM trades
        WHERE trader_id = :trader_id
        {symbol_filter}
        ORDER BY timestamp DESC
        LIMIT :limit
    """
    params: dict = {"trader_id": trader_id, "limit": limit}
    if symbol:
        query = base_q.format(symbol_filter="AND symbol = :symbol")
        params["symbol"] = symbol
    else:
        query = base_q.format(symbol_filter="")

    with get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    return df


def compute_trader_stats(df: pd.DataFrame) -> dict:
    """
    Summarise trader history into scalar metrics that the LLM prompt embeds.

    Returns an empty dict (not None) when the dataframe is empty so downstream
    code can check `if th:` without guarding against None.
    """
    if df.empty:
        return {}

    df = df.copy()
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    total = len(df)
    buy_count = int((df["side"].str.upper() == "BUY").sum())
    sell_count = total - buy_count

    return {
        "trade_count": total,
        "avg_price": (
            round(float(df["price"].mean()), 4)
            if not df["price"].isna().all()
            else None
        ),
        "avg_volume": (
            round(float(df["volume"].mean()), 2)
            if not df["volume"].isna().all()
            else None
        ),
        "off_hours_rate": (
            round(float(df["is_off_hours"].mean()), 4)
            if "is_off_hours" in df.columns
            else None
        ),
        "otc_rate": (
            round(float(df["is_otc"].mean()), 4)
            if "is_otc" in df.columns
            else None
        ),
        "buy_sell_ratio": (
            round(buy_count / sell_count, 4) if sell_count > 0 else None
        ),
        # Cross-day aggregation is needed for a reliable volume share; omit
        # rather than emit a misleading per-row approximation.
        "avg_trader_volume_share": None,
    }


def load_market_window(
    symbol: str,
    ts: datetime,
    window_minutes: int = 60,
) -> pd.DataFrame:
    """
    Load all trades for `symbol` in a ±window_minutes window around `ts`.

    Used to compute the relative volume spike and price deviation for the
    flagged trade versus the surrounding market activity.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    low = ts - timedelta(minutes=window_minutes)
    high = ts + timedelta(minutes=window_minutes)

    with get_engine().connect() as conn:
        df = pd.read_sql(
            text("""
                SELECT price, volume, timestamp
                FROM trades
                WHERE symbol = :symbol
                  AND timestamp BETWEEN :low AND :high
                ORDER BY timestamp
            """),
            conn,
            params={"symbol": symbol, "low": low, "high": high},
        )
    return df


def compute_market_context(window_df: pd.DataFrame, raw: dict) -> dict:
    """
    Compute context metrics relative to the flagged trade.

    Returns N/A-safe dict — every key is always present so the prompt
    template never emits KeyError.
    """
    empty = {
        "symbol_trade_count_window": 0,
        "symbol_avg_volume_window": "N/A",
        "symbol_avg_price_window": "N/A",
        "symbol_volume_spike": "N/A",
        "price_deviation_from_window_mean": "N/A",
    }
    if window_df.empty:
        return empty

    wdf = window_df.copy()
    wdf["volume"] = pd.to_numeric(wdf["volume"], errors="coerce")
    wdf["price"] = pd.to_numeric(wdf["price"], errors="coerce")

    avg_vol = float(wdf["volume"].mean())
    avg_price = float(wdf["price"].mean())
    trade_vol = float(raw.get("volume") or 0)
    trade_price = float(raw.get("price") or 0)

    return {
        "symbol_trade_count_window": len(wdf),
        "symbol_avg_volume_window": round(avg_vol, 2),
        "symbol_avg_price_window": round(avg_price, 4),
        "symbol_volume_spike": (
            round(trade_vol / avg_vol, 4) if avg_vol > 0 else "N/A"
        ),
        "price_deviation_from_window_mean": (
            round((trade_price - avg_price) / avg_price * 100, 4)
            if avg_price > 0
            else "N/A"
        ),
    }
