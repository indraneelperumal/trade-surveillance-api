"""
Feature Engineering Pipeline v2 — Supabase-native.

Replaces the original feature_engineering.py (which read from S3 NDJSON files).
This version reads the trades table directly from Supabase PostgreSQL via
SQLAlchemy, engineers 12 compliance-reviewed features, and uploads
features.parquet to Supabase Storage for anomaly_model_v2.py to consume.

Run:
    python -m trade_surveillance.pipelines.feature_engineering_v2

Prerequisites:
    pip install -e ".[dev,pipelines]"
    .env must have: DATABASE_URL, SUPABASE_URL,
                    SUPABASE_SERVICE_ROLE_KEY, SUPABASE_STORAGE_BUCKET

──────────────────────────────────────────────────────────────────────────
12 MODEL FEATURES (Phase 1 — compliance-reviewed)
──────────────────────────────────────────────────────────────────────────

Tier 1 — Loaded from trades (pre-computed by mock_data_script):
  price_vs_nbbo_bps   Execution deviation from NBBO mid — fat_finger / best
                      execution breach (MiFID II Art.27, FINRA 5310)
  adv_pct             Trade volume as % of instrument avg daily volume —
                      volume_spike signal
  is_off_hours        Outside NYSE hours 09:30–16:00 ET — off_hours signal
  is_otc              OTC venue — lower regulatory oversight, risk modifier

Tier 2 — Single-row computation (no groupby):
  depth_imbalance     (bid_size - ask_size) / (bid_size + ask_size)
                      Range [-1, +1]. Near ±1 = one-sided book — spoofing proxy
  trade_value_pct_risk_limit
                      trade_value / risk_limit_usd — direct risk limit breach

Tier 3 — GroupBy computations (require full dataset):
  z_score_price       (price - daily_mean) / daily_std per symbol×date
                      > 4σ → fat_finger
  z_score_volume      (volume - daily_mean) / daily_std per symbol×date
                      > 4σ → volume_spike
  trader_buy_sell_ratio  buy_count / total_count per trader×date
                      > 0.9 → wash_trade behavioural signal
  trader_volume_share trader_total_vol / symbol_total_vol per trader×symbol×date
                      > 0.25 → market concentration
  counterparty_daily_count  trades with same counterparty per trader×cpty×date
                      High repeat count → circular trading pattern

Tier 4 — Time-sort computation:
  return_vs_prev      ln(price / prev_price) per symbol ordered by timestamp
                      Large |value| → price discontinuity / fat_finger

Dropped after compliance review (not in FEATURE_COLS):
  ✗ relative_spread   — redundant with price_vs_nbbo_bps, dilutes SHAP output
  ✗ is_block_trade    — collinear with adv_pct + z_score_volume
  ✗ spread / mid_price — reference values, not anomaly signals
  ✗ inter_arrival_time — Phase 2 (algo burst / layering detection)
──────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import io
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

from trade_surveillance.config import get_settings
from trade_surveillance.db.migrator import get_engine
from trade_surveillance.storage import upload_bytes

# ── Columns fetched from the trades table ────────────────────────────────────
# Narrow SELECT — 17 cols instead of all 62 keeps the DB round-trip fast.
_DB_COLUMNS: list[str] = [
    # identity / join keys
    "trade_id",
    "timestamp",
    "trade_date",
    "symbol",
    "trader_id",
    "counterparty_id",
    # raw values for computed features
    "price",
    "volume",
    "trade_value",
    "side",            # "Buy" / "Sell"
    "bid_size",
    "ask_size",
    "risk_limit_usd",
    # Tier-1 features (already computed by mock_data_script, load as-is)
    "price_vs_nbbo_bps",
    "adv_pct",
    "is_off_hours",
    "is_otc",
]

# The 12 columns the anomaly model will consume.
# anomaly_model_v2.py must declare an identical FEATURE_COLS list.
FEATURE_COLS: list[str] = [
    "price_vs_nbbo_bps",
    "adv_pct",
    "is_off_hours",
    "is_otc",
    "depth_imbalance",
    "z_score_price",
    "z_score_volume",
    "trader_buy_sell_ratio",
    "trader_volume_share",
    "counterparty_daily_count",
    "return_vs_prev",
    "trade_value_pct_risk_limit",
]


# ─── STEP 1: LOAD FROM DATABASE ───────────────────────────────────────────────

def load_from_db() -> pd.DataFrame:
    """
    Load the 17 required columns from the trades table into a DataFrame.

    Uses SQLAlchemy engine from trade_surveillance.db.migrator — the same
    DATABASE_URL / pooler settings the API uses, including the
    prepare_threshold=None fix for Supabase transaction pooler (port 6543).

    Returns:
        DataFrame with one row per trade (~200k rows for the seeded dataset).
    """
    engine = get_engine()

    # Quote "timestamp" to avoid the SQL reserved-word conflict
    col_list = ", ".join(
        f'"{c}"' if c == "timestamp" else c for c in _DB_COLUMNS
    )
    query = f"SELECT {col_list} FROM trades"

    print(f"      Querying trades table ({len(_DB_COLUMNS)} columns) ...")
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)

    # psycopg3 returns UUID columns as Python uuid.UUID objects; PyArrow
    # serialises those as 16-byte binary in Parquet. Cast to str here so
    # the Parquet stores a plain UUID string and anomaly_model_v2 can insert
    # it directly into the alerts.trade_id UUID column without decoding.
    df["trade_id"] = df["trade_id"].astype(str)

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    # Guard: side casing must be "Buy" / "Sell" (matches mock_data_script line 388)
    unexpected_sides = (~df["side"].isin({"Buy", "Sell"})).sum()
    if unexpected_sides:
        warnings.warn(
            f"{unexpected_sides:,} rows have unexpected side values — "
            "trader_buy_sell_ratio will be set to neutral (0.5) for those rows."
        )

    print(f"      Loaded {len(df):,} trades × {df.shape[1]} columns")
    return df


# ─── STEP 2: ENGINEER FEATURES ────────────────────────────────────────────────

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all 12 model features from the raw trades DataFrame.

    Tier-1 features (price_vs_nbbo_bps, adv_pct, is_off_hours, is_otc) are
    already present — this function adds the remaining 8 in-place.

    Args:
        df: Output of load_from_db().

    Returns:
        df with all 12 FEATURE_COLS present and validated.
    """
    print("      Engineering features ...")

    # ── Tier 1: cast booleans so sklearn gets 0/1 not True/False ─────────────
    df["is_off_hours"] = df["is_off_hours"].astype(int)
    df["is_otc"]       = df["is_otc"].astype(int)

    # ── Tier 2a: depth_imbalance ─────────────────────────────────────────────
    # Measures order-book skew at execution time.
    # +1.0 = all bids (fake buy pressure), -1.0 = all asks (fake sell pressure)
    # Both extremes → spoofing proxy. Guard against zero-sum sizes.
    size_sum = df["bid_size"] + df["ask_size"]
    df["depth_imbalance"] = np.where(
        size_sum > 0,
        (df["bid_size"] - df["ask_size"]) / size_sum,
        0.0,
    )

    # ── Tier 2b: trade_value_pct_risk_limit ──────────────────────────────────
    # Direct risk-limit breach indicator.
    # Value > 1.0  → trade exceeded the trader's authorised mandate.
    df["trade_value_pct_risk_limit"] = np.where(
        df["risk_limit_usd"] > 0,
        df["trade_value"] / df["risk_limit_usd"],
        0.0,
    )

    # ── GroupBy anchor (reused for z-scores and volume share) ────────────────
    grp_sym_date = df.groupby(["symbol", "trade_date"], observed=True)

    # ── Tier 3a: z_score_price ───────────────────────────────────────────────
    # Standard-deviation distance of this trade's price from the symbol's
    # daily mean. ddof=1 for sample std. Single-trade groups → std=0 → 0.0.
    # std is computed once via walrus operator to avoid the double-call cost.
    df["z_score_price"] = grp_sym_date["price"].transform(
        lambda x: (x - x.mean()) / s
        if (s := x.std(ddof=1)) > 0
        else pd.Series(0.0, index=x.index)
    )

    # ── Tier 3b: z_score_volume ──────────────────────────────────────────────
    df["z_score_volume"] = grp_sym_date["volume"].transform(
        lambda x: (x - x.mean()) / s
        if (s := x.std(ddof=1)) > 0
        else pd.Series(0.0, index=x.index)
    )

    # ── Tier 3c: trader_volume_share ─────────────────────────────────────────
    # Aggregate each TRADER's total volume for the symbol-date, then divide
    # by the full symbol-date total. Using per-trade volume here would
    # undercount by ~N trades, making the feature useless for concentration
    # detection (bug caught in code review).
    total_sym_vol  = grp_sym_date["volume"].transform("sum")
    trader_sym_vol = df.groupby(
        ["trader_id", "symbol", "trade_date"], observed=True
    )["volume"].transform("sum")
    df["trader_volume_share"] = np.where(
        total_sym_vol > 0,
        trader_sym_vol / total_sym_vol,
        0.0,
    )

    # ── Tier 3d: trader_buy_sell_ratio ───────────────────────────────────────
    # Fraction of this trader's trades that were buys on a given day.
    # 0.0 = all sells, 1.0 = all buys. > 0.9 combined with high volume
    # is the wash_trade classification threshold in anomaly_model_v2.py.
    valid_mask = df["side"].isin({"Buy", "Sell"})
    valid = df[valid_mask].copy()

    buy_counts = (
        valid[valid["side"] == "Buy"]
        .groupby(["trader_id", "trade_date"], observed=True)
        .size()
        .rename("buy_count")
    )
    total_counts = (
        valid.groupby(["trader_id", "trade_date"], observed=True)
        .size()
        .rename("total_count")
    )
    ratio = (
        buy_counts.reindex(total_counts.index).fillna(0) / total_counts
    ).rename("trader_buy_sell_ratio")

    df = df.merge(ratio.reset_index(), on=["trader_id", "trade_date"], how="left")
    # Rows with unexpected side values get neutral 0.5
    df["trader_buy_sell_ratio"] = df["trader_buy_sell_ratio"].fillna(0.5)

    # ── Tier 3e: counterparty_daily_count ────────────────────────────────────
    # How many times this trader dealt with this exact counterparty today.
    # High repeat count is a structural wash-trade signal — the same two
    # parties trading back and forth is suspicious regardless of direction.
    cpty_counts = (
        df.groupby(["trader_id", "counterparty_id", "trade_date"], observed=True)
        .size()
        .rename("counterparty_daily_count")
        .reset_index()
    )
    df = df.merge(
        cpty_counts,
        on=["trader_id", "counterparty_id", "trade_date"],
        how="left",
    )
    df["counterparty_daily_count"] = (
        df["counterparty_daily_count"].fillna(1).astype(float)
    )

    # ── Tier 4: return_vs_prev ────────────────────────────────────────────────
    # Log return from the previous executed trade in the same symbol.
    # Large |value| = price discontinuity — fat_finger signal.
    # First trade per symbol has no prior price → fill with 0.0 (no return).
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    prev_price = df.groupby("symbol", observed=True)["price"].shift(1)
    df["return_vs_prev"] = np.where(
        (prev_price > 0) & (df["price"] > 0),
        np.log(df["price"] / prev_price),
        np.nan,
    )
    df["return_vs_prev"] = df["return_vs_prev"].fillna(0.0)

    # ── Validation ────────────────────────────────────────────────────────────
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"Feature engineering incomplete — missing columns: {missing}"
        )

    nan_summary = {
        c: int(df[c].isna().sum())
        for c in FEATURE_COLS
        if df[c].isna().any()
    }
    if nan_summary:
        warnings.warn(f"NaN values remain after engineering: {nan_summary}")

    print(f"      Features complete — DataFrame shape: {df.shape}")
    return df


# ─── STEP 3: UPLOAD TO SUPABASE STORAGE ──────────────────────────────────────

def write_features(df: pd.DataFrame) -> None:
    """
    Serialise the enriched DataFrame to Snappy-compressed Parquet and upload
    to Supabase Storage at SUPABASE_STORAGE_BUCKET / SUPABASE_FEATURES_KEY.

    anomaly_model_v2.py downloads this file to skip re-engineering features
    on every model run.

    Args:
        df: Output of engineer_features().
    """
    s = get_settings()

    table = pa.Table.from_pandas(df)
    buf   = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    size_mb = buf.tell() / 1_048_576
    buf.seek(0)

    print(
        f"      Uploading to {s.storage_bucket}/{s.features_key} "
        f"({len(df):,} rows, {size_mb:.1f} MB) ..."
    )
    upload_bytes(s.storage_bucket, s.features_key, buf.read())
    print("      Upload complete.")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 64)
    print("  trade_surveillance.pipelines.feature_engineering_v2")
    print("=" * 64)

    s = get_settings()
    print(f"\n  Source  : Supabase PostgreSQL — trades table")
    print(f"  Output  : {s.storage_bucket}/{s.features_key}")
    print(f"  Features: {len(FEATURE_COLS)}")
    print()

    print("[1/3] Loading trades from database ...")
    df = load_from_db()

    print("\n[2/3] Engineering features ...")
    df = engineer_features(df)

    print("\n  Feature statistics (model input columns):")
    for col in FEATURE_COLS:
        s_col = df[col]
        nan_note = f"  ⚠ {s_col.isna().sum()} NaN" if s_col.isna().any() else ""
        print(
            f"    {col:<35} "
            f"mean={s_col.mean():>9.4f}  "
            f"std={s_col.std():>8.4f}  "
            f"min={s_col.min():>9.4f}  "
            f"max={s_col.max():>9.4f}"
            f"{nan_note}"
        )

    print("\n[3/3] Writing features to Supabase Storage ...")
    write_features(df)

    s_cfg = get_settings()
    print("\n" + "─" * 64)
    print(f"  Rows written : {len(df):,}")
    print(f"  Feature cols : {len(FEATURE_COLS)}")
    print(f"  Storage path : {s_cfg.storage_bucket}/{s_cfg.features_key}")
    print("─" * 64)
    print("Done.\n")


if __name__ == "__main__":
    main()
