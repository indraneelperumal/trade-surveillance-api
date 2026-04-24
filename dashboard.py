import io
import json
import time
from datetime import datetime, timedelta, timezone

import boto3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

# ── Color constants ────────────────────────────────────────────────────────────
BG_PRIMARY = "#0d1117"
BG_CARD    = "#161b22"
BG_CARD2   = "#1c2128"
BORDER     = "#21262d"
GREEN      = "#00c805"
RED        = "#f85149"
YELLOW     = "#e3b341"
BLUE       = "#58a6ff"
TEXT       = "#e6edf3"
TEXT_DIM   = "#8b949e"
PURPLE     = "#bc8cff"

TYPE_COLORS = {
    "off_hours":    "#58a6ff",
    "volume_spike": "#f85149",
    "spoofing":     "#e3b341",
    "wash_trade":   "#bc8cff",
    "multi_flag":   "#e3b341",
    "unknown":      "#8b949e",
}

SYMBOLS = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA"]
BUCKET  = "trade-surveillance-bucket"

PLOTLY_LAYOUT = dict(
    paper_bgcolor=BG_PRIMARY,
    plot_bgcolor=BG_CARD,
    font_color=TEXT,
    margin=dict(l=20, r=20, t=40, b=20),
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# ── Data loading ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_anomalies() -> pd.DataFrame:
    try:
        s3  = boto3.client("s3")
        obj = s3.get_object(Bucket=BUCKET, Key="processed/anomalies.parquet")
        return pd.read_parquet(io.BytesIO(obj["Body"].read()))
    except Exception as exc:
        st.error(f"Failed to load anomalies.parquet: {exc}")
        st.stop()


@st.cache_data(ttl=300)
def load_memos_list() -> list:
    try:
        s3  = boto3.client("s3")
        res = s3.list_objects_v2(Bucket=BUCKET, Prefix="memos/")
        out = []
        for obj in res.get("Contents", []):
            if obj["Key"].endswith(".json"):
                trade_id = obj["Key"].split("/")[-1].replace(".json", "")
                out.append({
                    "trade_id":      trade_id,
                    "key":           obj["Key"],
                    "last_modified": obj["LastModified"],
                })
        return sorted(out, key=lambda x: x["last_modified"], reverse=True)
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_memo(trade_id: str) -> dict:
    try:
        s3  = boto3.client("s3")
        obj = s3.get_object(Bucket=BUCKET, Key=f"memos/{trade_id}.json")
        return json.loads(obj["Body"].read())
    except Exception:
        return {}


@st.cache_data(ttl=60)
def get_live_prices(symbols: tuple) -> dict:
    result = {}
    for sym in symbols:
        try:
            fi    = yf.Ticker(sym).fast_info
            price = getattr(fi, "last_price", None)
            prev  = getattr(fi, "previous_close", None)
            if price and prev and prev > 0:
                change = price - prev
                pct    = change / prev * 100
            else:
                change = None
                pct    = None
            result[sym] = {"price": price, "change": change, "pct_change": pct}
        except Exception:
            result[sym] = {"price": None, "change": None, "pct_change": None}
    return result


@st.cache_data(ttl=300)
def get_stock_history(symbol: str, period: str = "1mo") -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).history(period=period)
    except Exception:
        return pd.DataFrame()


# ── Agent ──────────────────────────────────────────────────────────────────────

def run_investigation(trade_id: str) -> dict:
    try:
        from agents import investigate_trade
        return investigate_trade(trade_id, auto_approve=True)
    except Exception as exc:
        return {"verdict": "ERROR", "error": str(exc), "compliance_memo": {}}


# ── CSS ────────────────────────────────────────────────────────────────────────

def inject_css() -> None:
    st.markdown(f"""
    <style>
        [data-testid="stAppViewContainer"] {{
            background-color: {BG_PRIMARY};
            color: {TEXT};
        }}
        [data-testid="stHeader"] {{
            display: none !important;
        }}
        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
        .main .block-container {{
            padding-top: 80px !important;
            padding-left: 24px !important;
            padding-right: 24px !important;
            max-width: 100% !important;
        }}
        .stTabs [data-baseweb="tab-list"] {{
            background-color: {BG_CARD};
            border-radius: 8px;
            padding: 4px;
            gap: 2px;
        }}
        .stTabs [data-baseweb="tab"] {{
            color: {TEXT_DIM} !important;
            background-color: transparent;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 500;
        }}
        .stTabs [aria-selected="true"] {{
            color: {TEXT} !important;
            background-color: {BG_CARD2};
        }}
        .stTabs [data-baseweb="tab-highlight"] {{
            background-color: {GREEN} !important;
        }}
        [data-testid="stMetric"] {{
            background-color: {BG_CARD};
            padding: 16px;
            border-radius: 8px;
            border: 1px solid {BORDER};
        }}
        .stButton > button {{
            background-color: {BG_CARD};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 6px;
        }}
        .stButton > button:hover {{
            border-color: {GREEN};
            color: {GREEN};
        }}
        .stSelectbox > div > div,
        .stMultiSelect > div > div {{
            background-color: {BG_CARD};
            color: {TEXT};
            border-color: {BORDER};
        }}
        .stTextInput > div > div > input {{
            background-color: {BG_CARD};
            color: {TEXT};
            border-color: {BORDER};
            font-size: 15px;
            padding: 10px 14px;
        }}
        [data-testid="stDownloadButton"] button {{
            background-color: {BG_CARD2};
            color: {BLUE};
            border: 1px solid {BLUE};
            border-radius: 6px;
        }}
        .stDataFrame {{ background-color: {BG_CARD}; }}
        .streamlit-expanderHeader {{
            background-color: {BG_CARD};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 6px;
        }}
        .streamlit-expanderContent {{
            background-color: {BG_CARD2};
            border: 1px solid {BORDER};
        }}
        .stRadio > div {{ color: {TEXT}; }}
        h1, h2, h3, h4, h5, h6 {{ color: {TEXT}; }}
        [data-testid="stMarkdownContainer"] * {{ color: {TEXT}; }}
        .stAlert {{ background-color: {BG_CARD}; border-color: {BORDER}; }}
        [data-testid="stSidebar"] {{
            background-color: {BG_CARD};
            border-right: 1px solid {BORDER};
        }}
        .stProgress > div > div > div {{ background-color: {GREEN}; }}
        hr {{ border-color: {BORDER}; }}
        div[data-testid="stRadio"] label {{ color: {TEXT} !important; }}
        div[data-testid="stRadio"] div[role="radiogroup"] span {{ color: {TEXT} !important; }}
    </style>
    """, unsafe_allow_html=True)


# ── Fixed top bar ──────────────────────────────────────────────────────────────

def render_top_bar(prices: dict) -> None:
    # Build ticker items (repeated twice for seamless loop)
    ticker_items = []
    for sym in SYMBOLS:
        d     = prices.get(sym, {})
        price = d.get("price")
        pct   = d.get("pct_change")
        if price is None:
            ticker_items.append(
                f'<span style="margin:0 24px;font-size:13px;font-weight:600;">'
                f'<span style="color:{TEXT_DIM};">{sym}</span>'
                f'<span style="color:{TEXT};"> -- </span>'
                f'</span>'
            )
        else:
            color = GREEN if (pct or 0) >= 0 else RED
            arrow = "▲" if (pct or 0) >= 0 else "▼"
            ticker_items.append(
                f'<span style="margin:0 24px;font-size:13px;font-weight:600;">'
                f'<span style="color:{TEXT_DIM};">{sym}</span>'
                f'<span style="color:{TEXT};"> ${price:.2f} </span>'
                f'<span style="color:{color};">{arrow}{abs(pct):.2f}%</span>'
                f'</span>'
            )
    single_pass = "".join(ticker_items)
    # Duplicate content for seamless infinite loop
    ticker_content = single_pass + single_pass

    time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

    st.markdown(f"""
    <style>
    @keyframes ticker-scroll {{
        0%   {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
    }}
    </style>
    <div style="
        position:fixed;top:0;left:0;right:0;height:60px;
        background:{BG_PRIMARY};border-bottom:1px solid {BORDER};
        display:flex;align-items:center;justify-content:space-between;
        padding:0 20px;z-index:99999;
        font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    ">
        <div style="
            display:flex;flex-direction:column;
            border-left:3px solid {GREEN};padding-left:10px;
            background:transparent;flex-shrink:0;
        ">
            <span style="color:{GREEN};font-size:20px;font-weight:900;
                         letter-spacing:2px;line-height:1;">
                ATS<sup style="font-size:10px;">®</sup>
            </span>
            <span style="color:{TEXT_DIM};font-size:7px;font-weight:700;
                         letter-spacing:1.5px;text-transform:uppercase;margin-top:2px;">
                Agentic Trade Surveillance
            </span>
        </div>
        <div style="overflow:hidden;white-space:nowrap;flex:1;margin:0 20px;">
            <div style="display:inline-block;animation:ticker-scroll 30s linear infinite;">
                {ticker_content}
            </div>
        </div>
        <div style="text-align:right;flex-shrink:0;">
            <div style="color:{TEXT_DIM};font-size:11px;">
                Last updated: {time_str}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Global markets panel ───────────────────────────────────────────────────────

def render_market_panel() -> None:
    now_utc    = datetime.now(timezone.utc)
    now_mins   = now_utc.hour * 60 + now_utc.minute
    is_weekday = now_utc.weekday() < 5

    markets = [
        {"name": "NYSE",        "flag": "🇺🇸", "hours": "13:30–20:00",
         "open": is_weekday and 13*60+30 <= now_mins < 20*60},
        {"name": "NASDAQ",      "flag": "🇺🇸", "hours": "13:30–20:00",
         "open": is_weekday and 13*60+30 <= now_mins < 20*60},
        {"name": "BATS",        "flag": "🇺🇸", "hours": "13:30–20:00",
         "open": is_weekday and 13*60+30 <= now_mins < 20*60},
        {"name": "Pre-Market",  "flag": "🇺🇸", "hours": "09:00–13:30",
         "open": is_weekday and 9*60 <= now_mins < 13*60+30},
        {"name": "After-Hours", "flag": "🇺🇸", "hours": "20:00–00:00",
         "open": is_weekday and 20*60 <= now_mins},
        {"name": "LSE",         "flag": "🇬🇧", "hours": "08:00–16:30",
         "open": is_weekday and 8*60 <= now_mins < 16*60+30},
        {"name": "TSE",         "flag": "🇯🇵", "hours": "00:00–06:30",
         "open": is_weekday and now_mins < 6*60+30},
        {"name": "XETRA",       "flag": "🇩🇪", "hours": "07:00–15:30",
         "open": is_weekday and 7*60 <= now_mins < 15*60+30},
        {"name": "HKEX",        "flag": "🇭🇰", "hours": "01:30–08:00",
         "open": is_weekday and 1*60+30 <= now_mins < 8*60},
    ]

    n_open   = sum(1 for m in markets if m["open"])
    n_closed = len(markets) - n_open

    with st.expander("🌍 Global Markets (UTC)", expanded=False):
        st.markdown(
            f'<div style="margin-bottom:8px;font-size:13px;">'
            f'<span style="color:{GREEN};">🟢 {n_open} Open</span>'
            f'&nbsp;&nbsp;·&nbsp;&nbsp;'
            f'<span style="color:{RED};">🔴 {n_closed} Closed</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        hdr = st.columns([0.5, 2, 2.5, 1])
        for col, label in zip(hdr, ["", "Exchange", "Hours (UTC)", "Status"]):
            col.markdown(
                f'<b style="color:{TEXT_DIM};font-size:12px;">{label}</b>',
                unsafe_allow_html=True,
            )
        for mkt in markets:
            c0, c1, c2, c3 = st.columns([0.5, 2, 2.5, 1])
            c0.write(mkt["flag"])
            c1.write(mkt["name"])
            c2.write(mkt["hours"])
            sc = GREEN if mkt["open"] else RED
            c3.markdown(
                f'<span style="color:{sc};font-weight:bold;">'
                f'{"OPEN" if mkt["open"] else "CLOSED"}</span>',
                unsafe_allow_html=True,
            )


# ── Tab 1 — Overview ───────────────────────────────────────────────────────────

def page_overview(df: pd.DataFrame, memos_list: list) -> None:
    verdicts    = st.session_state.get("verdicts", {})
    flagged_all = df[df["is_anomaly"]]

    # Progress card
    high_priority  = flagged_all[flagged_all["anomaly_rank"] <= 500]
    n_high         = len(high_priority)
    n_investigated = sum(1 for tid in high_priority["trade_id"] if tid in verdicts)
    n_escalated    = sum(1 for v in verdicts.values() if v == "ESCALATE")
    n_monitored    = sum(1 for v in verdicts.values() if v == "MONITOR")
    n_dismissed    = sum(1 for v in verdicts.values() if v == "DISMISS")
    progress_val   = n_investigated / max(n_high, 1)

    st.markdown(f"""
    <div style="
        background:{BG_CARD};border:1px solid {BORDER};
        border-left:4px solid {GREEN};border-radius:8px;
        padding:16px 24px;margin-bottom:12px;
        display:flex;justify-content:space-between;align-items:center;
    ">
        <div>
            <div style="color:{TEXT_DIM};font-size:11px;font-weight:700;
                        letter-spacing:1px;text-transform:uppercase;margin-bottom:4px;">
                Today's Progress
            </div>
            <div style="color:{TEXT};font-size:20px;font-weight:700;">
                Investigated <span style="color:{GREEN};">{n_investigated}</span>
                of {n_high:,} high-priority trades
            </div>
        </div>
        <div style="text-align:right;font-size:14px;line-height:2.2;">
            <span style="color:{RED};">🔴 {n_escalated} Escalated</span>&emsp;
            <span style="color:{YELLOW};">🟡 {n_monitored} Monitored</span>&emsp;
            <span style="color:{GREEN};">🟢 {n_dismissed} Dismissed</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.progress(progress_val)

    st.markdown("<div style='margin:20px 0 4px 0;'></div>", unsafe_allow_html=True)

    # KPI cards
    c1, c2, c3, c4 = st.columns(4)
    total_trades  = len(df)
    n_anomalies   = int(flagged_all.shape[0])
    anomaly_rate  = n_anomalies / max(total_trades, 1) * 100

    kpi_data = [
        (c1, "Total Trades",      f"{total_trades:,}",       TEXT),
        (c2, "Anomalies Flagged", f"{n_anomalies:,}",        RED),
        (c3, "Anomaly Rate",      f"{anomaly_rate:.1f}%",    YELLOW),
        (c4, "Memos Generated",   str(len(memos_list)),      BLUE),
    ]
    for col, label, value, color in kpi_data:
        col.markdown(f"""
        <div style="
            background:{BG_CARD};border:1px solid {BORDER};
            border-radius:8px;padding:20px;text-align:center;
        ">
            <div style="color:{TEXT_DIM};font-size:12px;font-weight:600;
                        letter-spacing:0.5px;text-transform:uppercase;margin-bottom:8px;">
                {label}
            </div>
            <div style="color:{color};font-size:32px;font-weight:800;line-height:1;">
                {value}
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)

    # Time period filter
    period = st.radio(
        "TIME PERIOD",
        ["Last 7 days", "Last 30 days", "All time"],
        horizontal=True,
        key="overview_period",
    )

    # Apply filter
    flagged = flagged_all.copy()
    if not flagged.empty:
        max_date = pd.to_datetime(flagged["date"]).max().date()
        if period == "Last 7 days":
            cutoff  = max_date - timedelta(days=7)
            flagged = flagged[pd.to_datetime(flagged["date"]).dt.date >= cutoff]
        elif period == "Last 30 days":
            cutoff  = max_date - timedelta(days=30)
            flagged = flagged[pd.to_datetime(flagged["date"]).dt.date >= cutoff]

    # Charts
    col_l, col_r = st.columns([3, 2])

    with col_l:
        if not flagged.empty:
            daily = flagged.groupby("date").size().reset_index(name="count")
            daily["date"] = pd.to_datetime(daily["date"])
            fig_line = px.line(
                daily, x="date", y="count",
                title="Daily Anomaly Volume",
                color_discrete_sequence=[BLUE],
            )
            fig_line.update_layout(**PLOTLY_LAYOUT)
            fig_line.update_traces(line_width=2)
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.info("No flagged trades in selected period.")

    with col_r:
        if not flagged.empty:
            type_counts = flagged["anomaly_type"].dropna().value_counts()
            labels = type_counts.index.tolist()
            values = type_counts.values.tolist()
            colors = [TYPE_COLORS.get(t, TEXT_DIM) for t in labels]
            fig_pie = go.Figure(go.Pie(
                labels=labels, values=values,
                hole=0.65,
                marker_colors=colors,
                textfont_color=TEXT,
                textfont_size=11,
            ))
            fig_pie.update_layout(
                title="Violation Types",
                legend=dict(orientation="v", x=1.0, font=dict(color=TEXT, size=11)),
                **PLOTLY_LAYOUT,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    # Recent escalations feed
    st.markdown(
        f'<div style="margin:20px 0 8px 0;">'
        f'<span style="color:{RED};font-size:16px;font-weight:700;">'
        f'🔴 Recent Escalations</span></div>',
        unsafe_allow_html=True,
    )

    if not memos_list:
        st.info("No investigations run yet. Go to Flagged Trades to investigate.")
        return

    escalate_items = []
    for m in memos_list[:20]:
        memo_data = load_memo(m["trade_id"])
        if memo_data.get("verdict") == "ESCALATE":
            rows = df[df["trade_id"] == m["trade_id"]]
            escalate_items.append({
                "symbol": rows.iloc[0]["symbol"]    if not rows.empty else "?",
                "trader": rows.iloc[0]["trader_id"] if not rows.empty else "?",
                "rule":   memo_data.get("rule_violated", "?"),
                "ts":     str(rows.iloc[0]["timestamp"])[:16] if not rows.empty else "?",
            })

    if not escalate_items:
        st.markdown(
            f'<div style="color:{TEXT_DIM};padding:12px;font-style:italic;">'
            f'No escalations yet.</div>',
            unsafe_allow_html=True,
        )
    else:
        for item in escalate_items[:5]:
            st.markdown(f"""
            <div style="
                background:{BG_CARD};border:1px solid {BORDER};
                border-left:4px solid {RED};border-radius:0 8px 8px 0;
                padding:10px 16px;margin:6px 0;
                display:flex;justify-content:space-between;align-items:center;
            ">
                <div style="display:flex;gap:24px;align-items:center;font-size:13px;">
                    <span style="color:{RED};font-weight:bold;">⚠ ESCALATE</span>
                    <b style="color:{TEXT};">{item["symbol"]}</b>
                    <span style="color:{TEXT_DIM};">{item["trader"]}</span>
                    <span style="color:{YELLOW};">{item["rule"]}</span>
                    <span style="color:{TEXT_DIM};font-size:12px;">{item["ts"]}</span>
                </div>
                <span style="
                    background:{hex_to_rgba(RED, 0.15)};
                    color:{RED};border:1px solid {RED};
                    padding:2px 10px;border-radius:10px;
                    font-size:11px;font-weight:bold;
                ">ESCALATE</span>
            </div>
            """, unsafe_allow_html=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="ATS® Trade Surveillance",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_css()

    # Session state initialization
    defaults = {
        "verdicts":            {},
        "memos":               {},
        "open_memos":          set(),
        "selected_symbol":     "All",
        "investigated_today":  set(),
        "last_ticker_refresh": time.time(),
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Load data
    df         = load_anomalies()
    memos_list = load_memos_list()
    n_flagged  = int(df["is_anomaly"].sum())
    n_memos    = len(memos_list)

    # Fixed top bar (renders over page content via z-index)
    prices = get_live_prices(tuple(SYMBOLS))
    render_top_bar(prices)

    # Global search bar
    st.text_input(
        "",
        placeholder="🔍  Search traders, symbols, trade IDs...",
        key="global_search",
        label_visibility="collapsed",
    )

    render_market_panel()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Overview",
        f"🚨 Flagged Trades ({n_flagged:,})",
        f"📋 Reports ({n_memos})",
        "📈 Market Context",
    ])

    with tab1:
        page_overview(df, memos_list)

    with tab2:
        st.markdown(
            f'<div style="color:{TEXT_DIM};text-align:center;padding:80px 0;font-size:16px;">'
            f'🚧 Coming soon — Session 2</div>',
            unsafe_allow_html=True,
        )

    with tab3:
        st.markdown(
            f'<div style="color:{TEXT_DIM};text-align:center;padding:80px 0;font-size:16px;">'
            f'🚧 Coming soon — Session 3</div>',
            unsafe_allow_html=True,
        )

    with tab4:
        st.markdown(
            f'<div style="color:{TEXT_DIM};text-align:center;padding:80px 0;font-size:16px;">'
            f'🚧 Coming soon — Session 4</div>',
            unsafe_allow_html=True,
        )

    # Footer
    st.markdown(
        "---\n"
        f"**ATS®** Agentic Trade Surveillance  ·  "
        f"152,010 trades monitored  ·  "
        f"IsolationForest + Claude AI  ·  "
        f"© 2026  ·  CONFIDENTIAL"
    )

    # Ticker auto-refresh every 60 seconds
    if time.time() - st.session_state.get("last_ticker_refresh", 0) >= 60:
        st.session_state["last_ticker_refresh"] = time.time()
        get_live_prices.clear()
        st.rerun()


if __name__ == "__main__":
    main()
