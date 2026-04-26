"""
lambda_function.py — Enterprise-grade synthetic trade generator.

Field design rationale:
  - RAW FIELDS (18 original): preserved exactly — feature_engineering.py depends on them
  - FEATURE-SEEDING FIELDS: fields that directly improve the 12 engineered features
    and IsolationForest recall (spread, depth_imbalance, z_score proxies, etc.)
  - COMPLIANCE CONTEXT FIELDS: fields the agent prompt and compliance officers need
    (trader desk/type, client type/LEI, counterparty, algo, regulatory flags)
  - EXCLUDED: pure reference data with no pipeline consumer
    (sedol, mic, tick_size, lot_size, exec_id, clearing_house, waiver_type)

Anomaly seeding design:
  - fat_finger    : z_score_price > 4  → GBM shock multiplier on volatile symbols
  - volume_spike  : z_score_volume > 4 → BLOCK tier + high intraday multiplier
  - off_hours     : is_off_hours=True  → off_hours_tendency per trader profile
  - spoofing      : |depth_imbalance| > 0.8 → spoof_bias skews bid/ask sizes
  - wash_trade    : trader_buy_sell_ratio > 0.9 AND z_score_volume > 2
                    → buy_side_bias close to 1.0 + LARGE/BLOCK volume tier
  - multi_flag    : 2+ conditions — naturally emerges from combined signals
"""

import os
import json
import uuid
import random
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import boto3
from sqlalchemy import create_engine, text

# ─── CONFIG ───────────────────────────────────────────────────────────────────
N_TRADES      = int(os.environ.get("NUM_TRADES", "200000"))
EXT_HOURS_PCT = float(os.environ.get("EXT_HOURS_PCT", "0.10"))
OTC_PCT       = float(os.environ.get("OTC_PCT", "0.15"))
OUTPUT_TARGET = os.environ.get("OUTPUT_TARGET", "database").strip().lower()
STREAM_NAME   = os.environ.get("STREAM_NAME", "")
DATABASE_URL  = os.environ.get("DATABASE_URL", "")
DB_BATCH_SIZE = int(os.environ.get("DB_BATCH_SIZE", "5000"))

MKT_OPEN  = (13, 30)   # UTC — NYSE 09:30 ET
MKT_CLOSE = (20, 0)    # UTC — NYSE 16:00 ET

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
kinesis = boto3.client("kinesis") if OUTPUT_TARGET == "kinesis" else None


# ─── INSTRUMENT UNIVERSE ──────────────────────────────────────────────────────
# isin, cusip, sector, industry, asset_class → memo context
# avg_daily_vol → adv_pct computation → volume_spike signal
# avg_spread_bps → seeds realistic bid/ask → spread + depth_imbalance features
# ann_vol → GBM volatility → realistic z_score_price distribution
# base_price → price walk initialisation

INSTRUMENTS = {
    "AAPL":  {"isin": "US0378331005", "cusip": "037833100", "sector": "Technology",        "industry": "Consumer Electronics",  "asset_class": "Equity", "market_cap": "large",  "base_price": 175.0,  "ann_vol": 0.25, "avg_spread_bps": 1.2, "avg_daily_vol": 55_000_000},
    "MSFT":  {"isin": "US5949181045", "cusip": "594918104", "sector": "Technology",        "industry": "Software",              "asset_class": "Equity", "market_cap": "large",  "base_price": 415.0,  "ann_vol": 0.28, "avg_spread_bps": 1.1, "avg_daily_vol": 20_000_000},
    "TSLA":  {"isin": "US88160R1014", "cusip": "88160R101", "sector": "Consumer Cyclical", "industry": "Auto Manufacturers",    "asset_class": "Equity", "market_cap": "large",  "base_price": 250.0,  "ann_vol": 0.65, "avg_spread_bps": 2.8, "avg_daily_vol": 90_000_000},
    "AMZN":  {"isin": "US0231351067", "cusip": "023135106", "sector": "Consumer Cyclical", "industry": "Internet Retail",       "asset_class": "Equity", "market_cap": "large",  "base_price": 185.0,  "ann_vol": 0.30, "avg_spread_bps": 1.3, "avg_daily_vol": 40_000_000},
    "NVDA":  {"isin": "US67066G1040", "cusip": "67066G104", "sector": "Technology",        "industry": "Semiconductors",        "asset_class": "Equity", "market_cap": "large",  "base_price": 875.0,  "ann_vol": 0.55, "avg_spread_bps": 1.5, "avg_daily_vol": 40_000_000},
    "GOOGL": {"isin": "US02079K3059", "cusip": "02079K305", "sector": "Communication",     "industry": "Internet Content",      "asset_class": "Equity", "market_cap": "large",  "base_price": 175.0,  "ann_vol": 0.27, "avg_spread_bps": 1.2, "avg_daily_vol": 25_000_000},
    "META":  {"isin": "US30303M1027", "cusip": "30303M102", "sector": "Communication",     "industry": "Social Media",          "asset_class": "Equity", "market_cap": "large",  "base_price": 505.0,  "ann_vol": 0.40, "avg_spread_bps": 1.4, "avg_daily_vol": 15_000_000},
    "JPM":   {"isin": "US46625H1005", "cusip": "46625H100", "sector": "Financial",         "industry": "Banks",                 "asset_class": "Equity", "market_cap": "large",  "base_price": 198.0,  "ann_vol": 0.22, "avg_spread_bps": 1.6, "avg_daily_vol": 8_000_000},
    "GS":    {"isin": "US38141G1040", "cusip": "38141G104", "sector": "Financial",         "industry": "Capital Markets",       "asset_class": "Equity", "market_cap": "large",  "base_price": 468.0,  "ann_vol": 0.25, "avg_spread_bps": 1.8, "avg_daily_vol": 2_000_000},
    "BAC":   {"isin": "US0605051046", "cusip": "060505104", "sector": "Financial",         "industry": "Banks",                 "asset_class": "Equity", "market_cap": "large",  "base_price": 38.0,   "ann_vol": 0.28, "avg_spread_bps": 1.5, "avg_daily_vol": 35_000_000},
    "XOM":   {"isin": "US30231G1022", "cusip": "30231G102", "sector": "Energy",            "industry": "Oil & Gas",             "asset_class": "Equity", "market_cap": "large",  "base_price": 115.0,  "ann_vol": 0.20, "avg_spread_bps": 1.4, "avg_daily_vol": 16_000_000},
    "JNJ":   {"isin": "US4781601046", "cusip": "478160104", "sector": "Healthcare",        "industry": "Drug Manufacturers",    "asset_class": "Equity", "market_cap": "large",  "base_price": 158.0,  "ann_vol": 0.15, "avg_spread_bps": 1.3, "avg_daily_vol": 7_000_000},
    "QQQ":   {"isin": "US46090E1038", "cusip": "46090E103", "sector": "Financial",         "industry": "ETF",                   "asset_class": "ETF",    "market_cap": "large",  "base_price": 445.0,  "ann_vol": 0.22, "avg_spread_bps": 0.8, "avg_daily_vol": 35_000_000},
    "SPY":   {"isin": "US78462F1030", "cusip": "78462F103", "sector": "Financial",         "industry": "ETF",                   "asset_class": "ETF",    "market_cap": "large",  "base_price": 510.0,  "ann_vol": 0.18, "avg_spread_bps": 0.5, "avg_daily_vol": 80_000_000},
}

SYMBOLS = list(INSTRUMENTS.keys())

# GBM price walk state — persists across calls in warm Lambda
_price_state = {
    sym: Decimal(str(inst["base_price"])).quantize(Decimal("0.01"))
    for sym, inst in INSTRUMENTS.items()
}


# ─── TRADER UNIVERSE ──────────────────────────────────────────────────────────
# trader_desk, trader_type, trader_region → memo: "who made this trade and why it matters"
# off_hours_tendency → directly seeds is_off_hours feature distribution
# avg_order_size → seeds volume tier → z_score_volume + trader_volume_share
# buy_side_bias → seeds trader_buy_sell_ratio feature (wash_trade rule)
# preferred_symbols → realistic clustering, improves z_score within-symbol variance

TRADER_PROFILES = {
    f"TR{i:04}": {
        "trader_id":          f"TR{i:04}",
        "trader_desk":        random.choice([
                                "EQUITY_FLOW", "EQUITY_ARBS", "STAT_ARB",
                                "ALGO_DESK", "SALES_TRADING", "PRIME_BROK",
                                "RETAIL_FLOW", "BLOCK_DESK",
                              ]),
        "trader_book":        f"BK{random.randint(1, 50):03}",
        "trader_region":      random.choice(["US_EAST", "US_WEST", "EMEA", "APAC"]),
        "trader_type":        random.choice([
                                "PROPRIETARY", "AGENCY", "MARKET_MAKER", "ALGO",
                              ]),
        "risk_limit_usd":     random.choice([
                                1_000_000, 5_000_000, 10_000_000, 50_000_000,
                              ]),
        "preferred_symbols":  random.sample(SYMBOLS, k=random.randint(2, 5)),
        "off_hours_tendency": round(random.uniform(0.0, 0.30), 3),
        "avg_order_size":     random.choice(["SMALL", "MEDIUM", "LARGE", "BLOCK"]),
        "buy_side_bias":      round(random.uniform(0.3, 0.95), 3),
    }
    for i in range(1, 201)
}

TRADER_IDS = list(TRADER_PROFILES.keys())


# ─── CLIENT UNIVERSE ──────────────────────────────────────────────────────────
# client_type → compliance risk tier (HEDGE_FUND vs RETAIL = very different scrutiny)
# client_lei → MiFID II reporting requirement — compliance officer needs this
# client_domicile → cross-border compliance flag
# client_mifid_category → determines applicable obligations
# aum_tier → helps compliance officer assess whether trade size is proportionate

CLIENT_PROFILES = {
    f"CL{i:05}": {
        "client_id":             f"CL{i:05}",
        "client_type":           random.choice([
                                   "HEDGE_FUND", "MUTUAL_FUND", "PENSION",
                                   "INSURANCE", "RETAIL", "FAMILY_OFFICE",
                                   "SOVEREIGN_WEALTH", "BROKER_DEALER",
                                 ]),
        "client_lei":            "".join(random.choices(
                                   "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=20
                                 )),
        "client_domicile":       random.choice([
                                   "US", "GB", "DE", "FR",
                                   "JP", "SG", "HK", "AU", "CA",
                                 ]),
        "client_mifid_category": random.choice([
                                   "PROFESSIONAL", "ELIGIBLE_COUNTERPARTY", "RETAIL",
                                 ]),
        "aum_tier":              random.choice([
                                   "<100M", "100M-1B", "1B-10B", "10B-100B", ">100B",
                                 ]),
    }
    for i in range(1, 501)
}

CLIENT_IDS = list(CLIENT_PROFILES.keys())


# ─── COUNTERPARTIES ───────────────────────────────────────────────────────────
# counterparty_id + counterparty_name → wash_trade detection:
# same counterparty appearing on both sides of similar trades = major red flag
# counterparty_lei → regulatory reporting field compliance officers file

COUNTERPARTIES = [
    {"counterparty_id": "CP001", "counterparty_name": "Goldman Sachs",       "counterparty_lei": "784F5XWPLTWKTBV3E584", "counterparty_type": "BROKER_DEALER"},
    {"counterparty_id": "CP002", "counterparty_name": "Morgan Stanley",      "counterparty_lei": "IGJSJL3JD5P30I6NJZ34", "counterparty_type": "BROKER_DEALER"},
    {"counterparty_id": "CP003", "counterparty_name": "JP Morgan",           "counterparty_lei": "7H6GLXDRUGQFU57RNE97", "counterparty_type": "BROKER_DEALER"},
    {"counterparty_id": "CP004", "counterparty_name": "Citadel Securities",  "counterparty_lei": "549300OUSL3JBLPQH836", "counterparty_type": "MARKET_MAKER"},
    {"counterparty_id": "CP005", "counterparty_name": "Virtu Financial",     "counterparty_lei": "549300KGFG6Z3OGEBN21", "counterparty_type": "MARKET_MAKER"},
    {"counterparty_id": "CP006", "counterparty_name": "Two Sigma",           "counterparty_lei": "549300WRF05DBVJMKM53", "counterparty_type": "HEDGE_FUND"},
    {"counterparty_id": "CP007", "counterparty_name": "Jane Street",         "counterparty_lei": "549300MRSDNKF6CTAH72", "counterparty_type": "MARKET_MAKER"},
    {"counterparty_id": "CP008", "counterparty_name": "Interactive Brokers", "counterparty_lei": "549300WG6CRPF1CZWH14", "counterparty_type": "BROKER_DEALER"},
]

# ─── ALGO STRATEGIES ──────────────────────────────────────────────────────────
# algo_strategy → memo context: DARK_SWEEP + SNIPER in off-hours elevates
# suspicion level for the compliance officer; TWAP/VWAP are standard and benign

ALGO_STRATEGIES = ["TWAP", "VWAP", "POV", "IS", "DARK_SWEEP", "ARRIVAL_PRICE", "CLOSE", "SNIPER", "NONE"]
ALGO_WEIGHTS    = [0.18,   0.22,   0.10,  0.08,  0.07,          0.06,            0.05,    0.04,    0.20]

# ─── VENUES ───────────────────────────────────────────────────────────────────
VENUE_WEIGHTS = {
    "NASDAQ": 0.32, "NYSE": 0.25, "BATS": 0.12, "ARCA": 0.10,
    "EDGX":   0.05, "IEX":  0.04, "DARK": 0.05, "ATS01": 0.03,
    "MEMX":   0.02, "OTC":  0.02,
}

ORDER_TYPE_WEIGHTS = {
    "Market": 0.45, "Limit": 0.38, "Stop": 0.08,
    "StopLimit": 0.05, "Pegged": 0.03, "MOC": 0.01,
}

MIFID_CAPACITY   = ["DEAL",  "AOTC",  "MTCH"]
MIFID_CAPACITY_W = [0.55,    0.35,    0.10]

# ─── ANOMALY SEEDING CONFIG ───────────────────────────────────────────────────
# Majority remain normal; anomalies are injected with realistic shapes.
ANOMALY_RATE = float(os.environ.get("ANOMALY_RATE", "0.12"))
ANOMALY_WEIGHTS = {
    "fat_finger": 0.20,
    "volume_spike": 0.24,
    "off_hours": 0.18,
    "spoofing": 0.16,
    "wash_trade": 0.12,
    "multi_flag": 0.10,
}


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _is_off_hours(ts: datetime) -> bool:
    """
    Exact same logic as feature_engineering.py is_off_hours.
    Using UTC directly (13:30-20:00 UTC = 09:30-16:00 ET).
    """
    mins       = ts.hour * 60 + ts.minute
    open_mins  = MKT_OPEN[0]  * 60 + MKT_OPEN[1]
    close_mins = MKT_CLOSE[0] * 60 + MKT_CLOSE[1]
    return not (open_mins <= mins < close_mins)


def pick_timestamp(trader: dict) -> datetime:
    now  = datetime.now(timezone.utc)
    date = now.date()
    off_prob = max(EXT_HOURS_PCT, trader["off_hours_tendency"])

    if random.random() < off_prob:
        h  = random.randint(4, MKT_OPEN[0] - 1) if random.random() < 0.4 else random.randint(MKT_CLOSE[0], 22)
        m  = random.randint(0, 59)
        s  = random.randint(0, 59)
        us = random.randint(0, 999_999)
        return datetime(date.year, date.month, date.day, h, m, s, us, tzinfo=timezone.utc)

    open_dt  = datetime(date.year, date.month, date.day, *MKT_OPEN,  0, tzinfo=timezone.utc)
    close_dt = datetime(date.year, date.month, date.day, *MKT_CLOSE, 0, tzinfo=timezone.utc)
    span     = int((close_dt - open_dt).total_seconds())
    return open_dt + timedelta(
        seconds=random.randint(0, span),
        microseconds=random.randint(0, 999_999),
    )


def pick_forced_offhours_timestamp() -> datetime:
    """Generate a timestamp guaranteed to be outside market hours."""
    now = datetime.now(timezone.utc)
    date = now.date()
    h = random.randint(4, MKT_OPEN[0] - 1) if random.random() < 0.5 else random.randint(MKT_CLOSE[0], 22)
    m = random.randint(0, 59)
    s = random.randint(0, 59)
    us = random.randint(0, 999_999)
    return datetime(date.year, date.month, date.day, h, m, s, us, tzinfo=timezone.utc)


def pick_anomaly_type() -> str | None:
    """Sample anomaly type with configured base anomaly rate."""
    if random.random() >= ANOMALY_RATE:
        return None
    labels = list(ANOMALY_WEIGHTS.keys())
    weights = list(ANOMALY_WEIGHTS.values())
    return random.choices(labels, weights=weights)[0]


def intraday_vol_multiplier(ts: datetime) -> float:
    """U-shaped intraday curve seeds realistic z_score_volume distribution."""
    mins       = ts.hour * 60 + ts.minute
    open_mins  = MKT_OPEN[0]  * 60 + MKT_OPEN[1]
    close_mins = MKT_CLOSE[0] * 60 + MKT_CLOSE[1]
    from_open  = max(0, mins - open_mins)
    to_close   = max(0, close_mins - mins)

    if _is_off_hours(ts):
        return random.uniform(0.3, 0.8)   # off-hours: thinly traded
    elif from_open < 30:
        return random.uniform(1.8, 3.5)   # opening burst
    elif to_close < 30:
        return random.uniform(2.0, 4.0)   # closing auction
    elif from_open < 90 or to_close < 90:
        return random.uniform(1.1, 1.8)
    else:
        return random.uniform(0.6, 1.1)   # midday lull


def simulate_price(symbol: str) -> tuple:
    """
    GBM price walk. Returns (mid_price, bid_price, ask_price, spread_bps).
    Spread dynamically widens with volatility — feeds spread, mid_price,
    relative_spread, and depth_imbalance features in feature_engineering.py.
    """
    inst        = INSTRUMENTS[symbol]
    ann_vol     = inst["ann_vol"]
    dt_frac     = 1.0 / (252 * 6.5 * 3600)
    shock       = Decimal(str(random.gauss(0, ann_vol * (dt_frac ** 0.5))))
    _price_state[symbol] = (
        _price_state[symbol] * (Decimal("1") + shock)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    mid         = _price_state[symbol]
    spread_bps  = inst["avg_spread_bps"] * random.uniform(0.7, 2.5)
    half_spread = (mid * Decimal(str(spread_bps / 10_000 / 2))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    bid = (mid - half_spread).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ask = (mid + half_spread).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(mid), float(bid), float(ask), round(spread_bps, 4)


def simulate_volume(symbol: str, ts: datetime, size_tier: str) -> int:
    """
    Volume by tier with intraday multiplier.
    BLOCK tier produces high adv_pct, directly seeding volume_spike detection.
    """
    ivol = intraday_vol_multiplier(ts)
    if size_tier == "BLOCK":
        return max(10_000, min(int(random.lognormvariate(9.5, 0.6) * ivol), 500_000))
    elif size_tier == "LARGE":
        return max(2_000,  min(int(random.lognormvariate(8.0, 0.8) * ivol), 50_000))
    elif size_tier == "MEDIUM":
        return max(100,    min(int(random.lognormvariate(6.5, 0.9) * ivol), 5_000))
    else:
        return max(1,      min(int(random.lognormvariate(4.5, 1.0)), 500))


def simulate_bid_ask_sizes(volume: int, spoof_bias: float = 0.0) -> tuple:
    """
    spoof_bias > 0.7 → heavily skewed sizes → |depth_imbalance| > 0.8
    which directly triggers the SPOOFING rule in anomaly_model.py.
    """
    if spoof_bias > 0.7:
        dominant  = int(volume * random.uniform(8, 15))
        recessive = max(1, int(volume * random.uniform(0.01, 0.08)))
        return (dominant, recessive) if random.random() < 0.5 else (recessive, dominant)
    bid_s = random.randint(max(1, volume // 4), volume * 3)
    ask_s = random.randint(max(1, volume // 4), volume * 3)
    return bid_s, ask_s


def gen_trade() -> dict:
    # ── Participants ──────────────────────────────────────────────────────────
    trader_id = random.choice(TRADER_IDS)
    client_id = random.choice(CLIENT_IDS)
    trader    = TRADER_PROFILES[trader_id]
    client    = CLIENT_PROFILES[client_id]
    cpty      = random.choice(COUNTERPARTIES)

    # ── Symbol ────────────────────────────────────────────────────────────────
    symbol = (
        random.choice(trader["preferred_symbols"])
        if trader["preferred_symbols"] and random.random() < 0.65
        else random.choice(SYMBOLS)
    )
    inst = INSTRUMENTS[symbol]

    anomaly_type = pick_anomaly_type()
    force_off_hours = anomaly_type in {"off_hours", "multi_flag"}

    # ── Timing ────────────────────────────────────────────────────────────────
    ts          = pick_forced_offhours_timestamp() if force_off_hours else pick_timestamp(trader)
    off_hours   = _is_off_hours(ts)
    settle_days = 1 if inst["asset_class"] == "ETF" else 2
    settle_date = (ts + timedelta(days=settle_days)).strftime("%Y-%m-%d")

    # ── Venue ─────────────────────────────────────────────────────────────────
    if random.random() < OTC_PCT:
        exchange = "OTC"
    else:
        venues, weights = zip(*VENUE_WEIGHTS.items())
        exchange = random.choices(venues, weights=weights)[0]
    is_otc = exchange == "OTC"

    # ── Price ─────────────────────────────────────────────────────────────────
    mid_price, bid_price, ask_price, spread_bps = simulate_price(symbol)
    # buy_side_bias seeds trader_buy_sell_ratio → wash_trade rule
    buy_bias = trader["buy_side_bias"]
    if anomaly_type in {"wash_trade", "multi_flag"}:
        buy_bias = max(buy_bias, random.uniform(0.92, 0.99))
    side  = "Buy" if random.random() < buy_bias else "Sell"
    price = ask_price if side == "Buy" else bid_price

    if anomaly_type in {"fat_finger", "multi_flag"}:
        # Strong jump to trigger z_score_price outliers.
        fat_finger_mult = random.choice([1.07, 1.10, 1.14, 0.93, 0.90, 0.86])
        price = round(price * fat_finger_mult, 2)
        mid_price = round(mid_price * fat_finger_mult, 2)
        bid_price = round(bid_price * fat_finger_mult, 2)
        ask_price = round(ask_price * fat_finger_mult, 2)

    # ── Volume ────────────────────────────────────────────────────────────────
    size_tier = trader["avg_order_size"]
    if anomaly_type in {"volume_spike", "wash_trade", "multi_flag"}:
        size_tier = random.choice(["LARGE", "BLOCK"])
    volume = simulate_volume(symbol, ts, size_tier)
    if anomaly_type in {"volume_spike", "multi_flag"}:
        volume = min(int(volume * random.uniform(2.2, 4.8)), 750_000)
    trade_value = round(price * volume, 2)

    # ── Bid/Ask sizes with spoofing tendency ──────────────────────────────────
    # BLOCK_DESK traders in off-hours have elevated spoofing probability
    spoof_prob = 0.12 if (trader["trader_desk"] == "BLOCK_DESK" and off_hours) else 0.04
    if anomaly_type in {"spoofing", "multi_flag"}:
        spoof_prob = max(spoof_prob, 0.95)
    spoof_bias = (
        random.uniform(0.8, 1.0) if random.random() < spoof_prob
        else random.uniform(0.0, 0.3)
    )
    bid_size, ask_size = simulate_bid_ask_sizes(volume, spoof_bias)

    # ── Order & algo metadata ─────────────────────────────────────────────────
    order_type    = random.choices(list(ORDER_TYPE_WEIGHTS), weights=list(ORDER_TYPE_WEIGHTS.values()))[0]
    algo_strategy = random.choices(ALGO_STRATEGIES, weights=ALGO_WEIGHTS)[0]
    algo_used     = algo_strategy != "NONE"

    # ── Regulatory ────────────────────────────────────────────────────────────
    mifid_capacity  = random.choices(MIFID_CAPACITY, weights=MIFID_CAPACITY_W)[0]
    short_sell_flag = random.choices(["", "SSEX", "SESH"], weights=[0.85, 0.10, 0.05])[0]

    # ── Market context ────────────────────────────────────────────────────────
    adv_pct        = round(volume / max(inst["avg_daily_vol"], 1) * 100, 4)
    is_block_trade = volume >= 10_000
    nbbo_bid       = round(bid_price * random.uniform(0.9995, 1.0), 2)
    nbbo_ask       = round(ask_price * random.uniform(1.0, 1.0005), 2)
    nbbo_mid       = round((nbbo_bid + nbbo_ask) / 2, 4)
    price_vs_nbbo_bps = round((price - nbbo_mid) / nbbo_mid * 10_000, 4) if nbbo_mid else 0.0

    # ── Commission ────────────────────────────────────────────────────────────
    commission_bps = (
        round(random.uniform(0.3, 1.5), 4)
        if client["client_type"] in ["HEDGE_FUND", "MUTUAL_FUND", "PENSION", "SOVEREIGN_WEALTH"]
        else round(random.uniform(1.5, 5.0), 4)
    )
    commission_usd = round(trade_value * commission_bps / 10_000, 2)

    return {
        # ══ ORIGINAL 18 RAW FIELDS — feature_engineering.py depends on these ══
        "trade_id":        str(uuid.uuid4()),
        "timestamp":       ts.isoformat(),
        "trade_time_ns":   int(ts.timestamp() * 1e9),
        "symbol":          symbol,
        "exchange":        exchange,
        "currency":        "USD",
        "price":           float(price),
        "volume":          volume,
        "trade_value":     trade_value,
        "side":            side,
        "order_type":      order_type,
        "liquidity_flag":  random.choice(["", "A", "R", "M"]),
        "trade_condition": random.choice(["", "", "", "F", "T", "Z", "@"]),
        "bid_price":       bid_price,
        "ask_price":       ask_price,
        "bid_size":        bid_size,
        "ask_size":        ask_size,
        "client_id":       client_id,
        "trader_id":       trader_id,

        # ══ FEATURE-SEEDING FIELDS ══
        # Pre-computed for Athena ad-hoc queries; feature_engineering.py
        # recomputes from raw fields — no conflict, just richer raw schema.
        "mid_price":          round(mid_price, 4),
        "spread":             round(ask_price - bid_price, 4),
        "spread_bps":         spread_bps,
        "relative_spread":    round((ask_price - bid_price) / mid_price, 6) if mid_price else 0,
        "nbbo_bid":           nbbo_bid,
        "nbbo_ask":           nbbo_ask,
        "nbbo_mid":           nbbo_mid,
        "price_vs_nbbo_bps":  price_vs_nbbo_bps,  # fat_finger signal
        "adv_pct":            adv_pct,              # volume_spike signal
        "is_block_trade":     is_block_trade,
        "is_off_hours":       off_hours,            # same logic as feature_engineering.py
        "is_otc":             is_otc,
        "trade_date":         ts.strftime("%Y-%m-%d"),
        "settlement_date":    settle_date,

        # ══ COMPLIANCE CONTEXT FIELDS — agent memo + compliance officer review ══

        # Instrument identity — memo must cite ISIN/CUSIP for regulatory filings
        "isin":               inst["isin"],
        "cusip":              inst["cusip"],
        "sector":             inst["sector"],
        "industry":           inst["industry"],
        "asset_class":        inst["asset_class"],
        "market_cap":         inst["market_cap"],

        # Trader context — "who made this trade, from which desk, under what mandate"
        "trader_desk":        trader["trader_desk"],
        "trader_book":        trader["trader_book"],
        "trader_region":      trader["trader_region"],
        "trader_type":        trader["trader_type"],
        "risk_limit_usd":     trader["risk_limit_usd"],

        # Client context — risk tier, reporting obligations, proportionality check
        "client_type":            client["client_type"],
        "client_lei":             client["client_lei"],
        "client_domicile":        client["client_domicile"],
        "client_mifid_category":  client["client_mifid_category"],
        "aum_tier":               client["aum_tier"],

        # Counterparty — wash_trade: same counterparty on both sides = red flag
        "counterparty_id":    cpty["counterparty_id"],
        "counterparty_name":  cpty["counterparty_name"],
        "counterparty_lei":   cpty["counterparty_lei"],
        "counterparty_type":  cpty["counterparty_type"],

        # Algo — DARK_SWEEP/SNIPER in off-hours elevates memo suspicion level
        "algo_strategy":      algo_strategy,
        "algo_used":          algo_used,
        "order_id":           str(uuid.uuid4()),
        "parent_order_id":    str(uuid.uuid4()),

        # MiFID II — compliance officer regulatory filing fields
        "mifid_capacity":     mifid_capacity,
        "short_sell_flag":    short_sell_flag,

        # Cost analysis — compliance officer proportionality and best execution check
        "commission_bps":     commission_bps,
        "commission_usd":     commission_usd,
        "market_impact_bps":  round(adv_pct * random.uniform(0.5, 2.0), 4),
        # Not persisted to table yet, but useful for QA / recall checks.
        "seeded_anomaly_type": anomaly_type or "normal",
    }


def _normalize_db_url(db_url: str) -> str:
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    parts = urlsplit(db_url)
    query_pairs = [(k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True) if k != "pgbouncer"]
    clean_query = urlencode(query_pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, clean_query, parts.fragment))


def _seed_reference_tables(conn) -> None:
    instrument_rows = []
    for symbol, inst in INSTRUMENTS.items():
        instrument_rows.append(
            {
                "symbol": symbol,
                "isin": inst["isin"],
                "cusip": inst["cusip"],
                "sector": inst["sector"],
                "industry": inst["industry"],
                "asset_class": inst["asset_class"],
                "market_cap": inst["market_cap"],
                "base_price": inst["base_price"],
                "ann_vol": inst["ann_vol"],
                "avg_spread_bps": inst["avg_spread_bps"],
                "avg_daily_vol": inst["avg_daily_vol"],
            }
        )
    conn.execute(
        text(
            """
            INSERT INTO instruments
            (symbol, isin, cusip, sector, industry, asset_class, market_cap, base_price, ann_vol, avg_spread_bps, avg_daily_vol)
            VALUES
            (:symbol, :isin, :cusip, :sector, :industry, :asset_class, :market_cap, :base_price, :ann_vol, :avg_spread_bps, :avg_daily_vol)
            ON CONFLICT (symbol) DO UPDATE SET
                isin = EXCLUDED.isin,
                cusip = EXCLUDED.cusip,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                asset_class = EXCLUDED.asset_class,
                market_cap = EXCLUDED.market_cap,
                base_price = EXCLUDED.base_price,
                ann_vol = EXCLUDED.ann_vol,
                avg_spread_bps = EXCLUDED.avg_spread_bps,
                avg_daily_vol = EXCLUDED.avg_daily_vol
            """
        ),
        instrument_rows,
    )

    trader_rows = []
    for trader in TRADER_PROFILES.values():
        trader_rows.append(
            {
                "trader_id": trader["trader_id"],
                "trader_desk": trader["trader_desk"],
                "trader_book": trader["trader_book"],
                "trader_region": trader["trader_region"],
                "trader_type": trader["trader_type"],
                "risk_limit_usd": trader["risk_limit_usd"],
                "preferred_symbols": trader["preferred_symbols"],
                "off_hours_tendency": trader["off_hours_tendency"],
                "avg_order_size": trader["avg_order_size"],
                "buy_side_bias": trader["buy_side_bias"],
            }
        )
    conn.execute(
        text(
            """
            INSERT INTO traders
            (trader_id, trader_desk, trader_book, trader_region, trader_type, risk_limit_usd, preferred_symbols, off_hours_tendency, avg_order_size, buy_side_bias)
            VALUES
            (:trader_id, :trader_desk, :trader_book, :trader_region, :trader_type, :risk_limit_usd, :preferred_symbols, :off_hours_tendency, :avg_order_size, :buy_side_bias)
            ON CONFLICT (trader_id) DO UPDATE SET
                trader_desk = EXCLUDED.trader_desk,
                trader_book = EXCLUDED.trader_book,
                trader_region = EXCLUDED.trader_region,
                trader_type = EXCLUDED.trader_type,
                risk_limit_usd = EXCLUDED.risk_limit_usd,
                preferred_symbols = EXCLUDED.preferred_symbols,
                off_hours_tendency = EXCLUDED.off_hours_tendency,
                avg_order_size = EXCLUDED.avg_order_size,
                buy_side_bias = EXCLUDED.buy_side_bias
            """
        ),
        trader_rows,
    )

    client_rows = list(CLIENT_PROFILES.values())
    conn.execute(
        text(
            """
            INSERT INTO clients
            (client_id, client_type, client_lei, client_domicile, client_mifid_category, aum_tier)
            VALUES
            (:client_id, :client_type, :client_lei, :client_domicile, :client_mifid_category, :aum_tier)
            ON CONFLICT (client_id) DO UPDATE SET
                client_type = EXCLUDED.client_type,
                client_lei = EXCLUDED.client_lei,
                client_domicile = EXCLUDED.client_domicile,
                client_mifid_category = EXCLUDED.client_mifid_category,
                aum_tier = EXCLUDED.aum_tier
            """
        ),
        client_rows,
    )

    conn.execute(
        text(
            """
            INSERT INTO counterparties
            (counterparty_id, counterparty_name, counterparty_lei, counterparty_type)
            VALUES
            (:counterparty_id, :counterparty_name, :counterparty_lei, :counterparty_type)
            ON CONFLICT (counterparty_id) DO UPDATE SET
                counterparty_name = EXCLUDED.counterparty_name,
                counterparty_lei = EXCLUDED.counterparty_lei,
                counterparty_type = EXCLUDED.counterparty_type
            """
        ),
        COUNTERPARTIES,
    )


_TRADES_INSERT_SQL = text(
    """
    INSERT INTO trades (
        trade_id, "timestamp", trade_time_ns, symbol, exchange, currency, price, volume, trade_value, side,
        order_type, liquidity_flag, trade_condition, bid_price, ask_price, bid_size, ask_size, client_id, trader_id,
        mid_price, spread, spread_bps, relative_spread, nbbo_bid, nbbo_ask, nbbo_mid, price_vs_nbbo_bps, adv_pct,
        is_block_trade, is_off_hours, is_otc, trade_date, settlement_date, isin, cusip, sector, industry, asset_class,
        market_cap, trader_desk, trader_book, trader_region, trader_type, risk_limit_usd, client_type, client_lei,
        client_domicile, client_mifid_category, aum_tier, counterparty_id, counterparty_name, counterparty_lei,
        counterparty_type, algo_strategy, algo_used, order_id, parent_order_id, mifid_capacity, short_sell_flag,
        commission_bps, commission_usd, market_impact_bps
    ) VALUES (
        :trade_id, :timestamp, :trade_time_ns, :symbol, :exchange, :currency, :price, :volume, :trade_value, :side,
        :order_type, :liquidity_flag, :trade_condition, :bid_price, :ask_price, :bid_size, :ask_size, :client_id, :trader_id,
        :mid_price, :spread, :spread_bps, :relative_spread, :nbbo_bid, :nbbo_ask, :nbbo_mid, :price_vs_nbbo_bps, :adv_pct,
        :is_block_trade, :is_off_hours, :is_otc, :trade_date, :settlement_date, :isin, :cusip, :sector, :industry, :asset_class,
        :market_cap, :trader_desk, :trader_book, :trader_region, :trader_type, :risk_limit_usd, :client_type, :client_lei,
        :client_domicile, :client_mifid_category, :aum_tier, :counterparty_id, :counterparty_name, :counterparty_lei,
        :counterparty_type, :algo_strategy, :algo_used, :order_id, :parent_order_id, :mifid_capacity, :short_sell_flag,
        :commission_bps, :commission_usd, :market_impact_bps
    )
    ON CONFLICT (trade_id) DO NOTHING
    """
)


def lambda_handler(event, context):
    if OUTPUT_TARGET == "database":
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL is required when OUTPUT_TARGET=database")
        engine = create_engine(_normalize_db_url(DATABASE_URL), future=True)
        written = 0
        with engine.begin() as conn:
            _seed_reference_tables(conn)
            batch: list[dict] = []
            for i in range(1, N_TRADES + 1):
                batch.append(gen_trade())
                if len(batch) >= DB_BATCH_SIZE:
                    conn.execute(_TRADES_INSERT_SQL, batch)
                    written += len(batch)
                    logging.info(f"Inserted {written}/{N_TRADES} trades...")
                    batch = []
            if batch:
                conn.execute(_TRADES_INSERT_SQL, batch)
                written += len(batch)
        logging.info(f"Inserted {written} trades into Postgres")
        return {"status": "ok", "written": written, "target": "database"}

    if OUTPUT_TARGET != "kinesis":
        raise ValueError("OUTPUT_TARGET must be either 'database' or 'kinesis'")
    if not STREAM_NAME:
        raise ValueError("STREAM_NAME is required when OUTPUT_TARGET=kinesis")

    records = []
    for _ in range(N_TRADES):
        trade = gen_trade()
        records.append({
            "PartitionKey": trade["symbol"],
            "Data":         json.dumps(trade, default=str),
        })

    resp   = kinesis.put_records(Records=records, StreamName=STREAM_NAME)
    failed = resp.get("FailedRecordCount", 0)
    if failed:
        logging.error(f"{failed} writes failed: %s", resp["Records"])
        raise Exception(f"{failed} records failed")

    logging.info(f"Published {N_TRADES - failed} trades to {STREAM_NAME}")
    return {"status": "ok", "published": N_TRADES - failed}
