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


@st.cache_data(ttl=300, show_spinner=False)
def load_trade_summary() -> pd.DataFrame:
    try:
        s3  = boto3.client("s3")
        obj = s3.get_object(Bucket=BUCKET, Key="processed/anomalies.parquet")
        return pd.read_parquet(
            io.BytesIO(obj["Body"].read()),
            columns=[
                "trade_id", "symbol", "trader_id",
                "client_id", "timestamp", "exchange",
                "side", "volume", "price",
                "anomaly_rank", "anomaly_score",
                "anomaly_type", "is_anomaly",
                "top_shap_feature", "order_type",
                "is_off_hours", "date",
            ],
        )
    except Exception as e:
        st.error(f"Load failed: {e}")
        st.stop()


@st.cache_data(ttl=60, show_spinner=False)
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


@st.cache_data(ttl=300, show_spinner=False)
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


# ── UI helpers ─────────────────────────────────────────────────────────────────

def time_ago(ts) -> str:
    try:
        dt    = pd.to_datetime(ts, utc=True)
        now   = pd.Timestamp.now(tz="UTC")
        delta = now - dt
        days  = delta.days
        if days >= 30:
            return f"{days // 30}mo ago"
        if days >= 1:
            return f"{days}d ago"
        if delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        return f"{delta.seconds // 60}m ago"
    except Exception:
        return ""


RULE_BADGE_COLORS = {
    "FAT_FINGER":   RED,
    "VOLUME_SPIKE": RED,
    "OFF_HOURS":    BLUE,
    "SPOOFING":     YELLOW,
    "WASH_TRADE":   PURPLE,
}


def get_matched_rules(row, memo=None):
    if memo:
        rv    = memo.get("rule_violated", "")
        found = [r for r in RULE_BADGE_COLORS if r in rv.upper()]
        if found:
            return found
    atype    = str(row.get("anomaly_type", "")).lower()
    rule_map = {
        "off_hours":    ["OFF_HOURS"],
        "volume_spike": ["VOLUME_SPIKE"],
        "fat_finger":   ["FAT_FINGER"],
        "spoofing":     ["SPOOFING"],
        "wash_trade":   ["WASH_TRADE"],
        "multi_flag":   ["VOLUME_SPIKE", "OFF_HOURS"],
    }
    return rule_map.get(atype, [atype.replace("_", " ").upper()])


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
            f'<span style="color:{RED};">● {n_closed} Closed</span>'
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

    # ── Progress card ─────────────────────────────────────────────────────────
    high_priority  = flagged_all[flagged_all["anomaly_rank"] <= 500]
    n_high         = len(high_priority)
    n_investigated = sum(1 for tid in high_priority["trade_id"] if tid in verdicts)
    n_escalated    = sum(1 for v in verdicts.values() if v == "ESCALATE")
    n_monitored    = sum(1 for v in verdicts.values() if v == "MONITOR")
    n_dismissed    = sum(1 for v in verdicts.values() if v == "DISMISS")
    progress_val   = min(len(st.session_state.get("investigated_today", set())) / 500, 1.0)

    st.markdown(f"""
    <div style="background:{BG_CARD};border:1px solid {BORDER};border-left:4px solid {GREEN};
                border-radius:8px;padding:20px 24px;margin-bottom:4px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div style="color:{TEXT_DIM};font-size:11px;font-weight:700;letter-spacing:1px;
                      text-transform:uppercase;margin-bottom:6px">Today's Progress</div>
          <div style="color:{TEXT};font-size:18px;font-weight:700">
            Investigated <span style="color:{GREEN}">{n_investigated}</span>
            of {n_high:,} high-priority trades
          </div>
        </div>
        <div style="display:flex;gap:28px;font-size:14px">
          <span>● <span style="color:{RED}">{n_escalated} Escalated</span></span>
          <span>● <span style="color:{YELLOW}">{n_monitored} Monitored</span></span>
          <span>● <span style="color:{GREEN}">{n_dismissed} Dismissed</span></span>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.progress(progress_val)
    st.markdown("<div style='margin:16px 0 4px'></div>", unsafe_allow_html=True)

    # ── KPI cards ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    total_trades = len(df)
    n_anomalies  = int(flagged_all.shape[0])
    anomaly_rate = n_anomalies / max(total_trades, 1) * 100

    for col, label, value, color in [
        (c1, "Total Trades",    f"{total_trades:,}",    TEXT),
        (c2, "Flagged",         f"{n_anomalies:,}",     RED),
        (c3, "Anomaly Rate",    f"{anomaly_rate:.1f}%", YELLOW),
        (c4, "Memos Generated", str(len(memos_list)),   BLUE),
    ]:
        col.markdown(f"""
        <div style="background:{BG_CARD};border:1px solid {BORDER};border-radius:8px;padding:20px">
          <div style="color:{TEXT_DIM};font-size:11px;font-weight:700;letter-spacing:1px;
                      text-transform:uppercase;margin-bottom:10px">{label}</div>
          <div style="color:{color};font-size:34px;font-weight:800;line-height:1">{value}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='margin:16px 0'></div>", unsafe_allow_html=True)

    # ── Time period filter ────────────────────────────────────────────────────
    period = st.radio(
        "TIME PERIOD", ["Last 7 days", "Last 30 days", "All time"],
        horizontal=True, index=1, key="overview_period",
    )
    flagged = flagged_all.copy()
    if not flagged.empty:
        max_date = pd.to_datetime(flagged["date"]).max().date()
        if period == "Last 7 days":
            cutoff  = max_date - timedelta(days=7)
            flagged = flagged[pd.to_datetime(flagged["date"]).dt.date >= cutoff]
        elif period == "Last 30 days":
            cutoff  = max_date - timedelta(days=30)
            flagged = flagged[pd.to_datetime(flagged["date"]).dt.date >= cutoff]

    # ── Charts ────────────────────────────────────────────────────────────────
    col_l, col_r = st.columns([3, 2])

    with col_l:
        if not flagged.empty:
            daily = flagged.groupby("date").size().reset_index(name="count")
            daily["date"] = pd.to_datetime(daily["date"])
            fig_bar = px.bar(daily, x="date", y="count",
                             title="Daily anomaly volume",
                             color_discrete_sequence=[BLUE])
            fig_bar.update_layout(**PLOTLY_LAYOUT, showlegend=False)
            fig_bar.update_traces(marker_line_width=0)
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("No flagged trades in selected period.")

    with col_r:
        if not flagged.empty:
            type_counts = flagged["anomaly_type"].dropna().value_counts()
            labels_raw  = type_counts.index.tolist()
            values      = type_counts.values.tolist()
            colors      = [TYPE_COLORS.get(t, TEXT_DIM) for t in labels_raw]
            label_map   = {
                "off_hours": "Off hours", "volume_spike": "Volume spike",
                "multi_flag": "Multi flag", "spoofing": "Spoofing",
                "wash_trade": "Wash trade", "fat_finger": "Fat finger",
                "unknown": "Other",
            }
            labels_disp = [
                f"{label_map.get(l, l.replace('_',' ').title())} {v:,}"
                for l, v in zip(labels_raw, values)
            ]
            fig_pie = go.Figure(go.Pie(
                labels=labels_disp, values=values,
                hole=0.65, marker_colors=colors, textinfo="none",
            ))
            fig_pie.update_layout(
                title="Violation types",
                legend=dict(orientation="v", x=0.70, y=0.5,
                            font=dict(color=TEXT, size=12)),
                **PLOTLY_LAYOUT,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    # ── Recent escalations ────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="border:1px solid {BORDER};border-radius:8px;padding:20px;margin-top:8px">
      <div style="color:{RED};font-size:16px;font-weight:700;margin-bottom:12px">
        Recent escalations
      </div>
    """, unsafe_allow_html=True)

    escalate_items = []
    for m in memos_list[:20]:
        memo_data = load_memo(m["trade_id"])
        if memo_data.get("verdict") == "ESCALATE":
            rows = df[df["trade_id"] == m["trade_id"]]
            if not rows.empty:
                r0  = rows.iloc[0]
                rv  = memo_data.get("rule_violated", "")
                rls = [x for x in ["FAT_FINGER","VOLUME_SPIKE","OFF_HOURS","SPOOFING","WASH_TRADE"]
                       if x in rv.upper()]
                if not rls:
                    rls = [rv[:24]] if rv else ["UNKNOWN"]
                try:
                    ts_fmt = pd.to_datetime(r0["timestamp"]).strftime("%b %d %Y · %H:%M UTC")
                except Exception:
                    ts_fmt = str(r0["timestamp"])[:16]
                escalate_items.append({
                    "trade_id": m["trade_id"],
                    "symbol":   r0["symbol"],
                    "trader":   r0["trader_id"],
                    "client":   str(r0.get("client_id", "")),
                    "rules":    rls,
                    "ts":       ts_fmt,
                })

    if not escalate_items:
        st.markdown(
            f'<p style="color:{TEXT_DIM};font-style:italic;font-size:13px;margin:0">'
            f'No other escalations yet — go to Flagged Trades to investigate.</p>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for item in escalate_items[:5]:
        rules_html = " · ".join(
            f'<span style="color:{YELLOW};font-weight:700">{r}</span>'
            for r in item["rules"]
        )
        info_col, btn_col = st.columns([7, 1])
        info_col.markdown(f"""
        <div style="border-left:4px solid {RED};padding:10px 16px;margin:4px 0;
                    display:flex;gap:18px;align-items:center;flex-wrap:wrap">
          <span style="color:{RED};border:1px solid {RED};border-radius:6px;
                       padding:3px 10px;font-size:11px;font-weight:800">ESCALATE</span>
          <b style="color:{TEXT};font-size:15px">{item["symbol"]}</b>
          <span style="color:{TEXT_DIM};font-size:13px">{item["trader"]} · {item["client"]}</span>
          <span style="font-size:12px">{rules_html}</span>
          <span style="color:{TEXT_DIM};font-size:12px">{item["ts"]}</span>
        </div>
        """, unsafe_allow_html=True)
        btn_col.button("View memo", key=f"vm_{item['trade_id']}")

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(
        f'<p style="color:{TEXT_DIM};font-style:italic;font-size:13px;margin:10px 0 0">'
        f'No other escalations yet — go to Flagged Trades to investigate.</p>',
        unsafe_allow_html=True,
    )


# ── Trade detail panel ─────────────────────────────────────────────────────────

def _render_trade_detail(row, memo, verdict, vc, n_flagged):
    trade_value = float(row["volume"]) * float(row["price"])
    tv_str = f"${trade_value / 1e6:.2f}M" if trade_value >= 1e6 else f"${trade_value:,.0f}"

    try:
        dt      = pd.to_datetime(row["timestamp"], utc=True)
        dt_str  = dt.strftime("%A, %b %d %Y")
        tm_str  = dt.strftime("%H:%M:%S UTC")
        ago_str = time_ago(row["timestamp"])
    except Exception:
        dt_str  = str(row["timestamp"])[:10]
        tm_str  = str(row["timestamp"])[11:19]
        ago_str = ""

    off_h     = bool(row.get("is_off_hours", False))
    off_badge = (
        f'<div style="display:inline-block;background:{YELLOW}22;color:{YELLOW};'
        f'border:1px solid {YELLOW};border-radius:6px;padding:5px 12px;'
        f'font-size:12px;margin:8px 0">&#9203; Off-hours (outside 13:30–20:00 UTC)</div>'
        if off_h else ""
    )
    side_col   = GREEN if str(row["side"]).lower() == "buy" else RED
    rules      = get_matched_rules(row, memo)
    rules_html = "".join(
        f'<span style="background:{RULE_BADGE_COLORS.get(r, TEXT_DIM)}22;'
        f'color:{RULE_BADGE_COLORS.get(r, TEXT_DIM)};'
        f'border:1px solid {RULE_BADGE_COLORS.get(r, TEXT_DIM)};'
        f'border-radius:12px;padding:3px 10px;font-size:11px;font-weight:700;'
        f'margin-right:6px">{r.replace("_"," ")}</span>'
        for r in rules
    )
    shap_txt = str(row.get("top_shap_feature", "—")).replace("_", " ")
    rank_txt = f'#{int(row["anomaly_rank"])} of {n_flagged:,}'

    det_col, why_col = st.columns(2)

    with det_col:
        st.markdown(f"""
        <div style="background:{BG_CARD2};border:1px solid {BORDER};border-radius:8px;
                    padding:20px;margin:6px 0 12px">
          <div style="color:{TEXT_DIM};font-size:10px;font-weight:700;letter-spacing:1px;margin-bottom:4px">EXECUTED</div>
          <div style="color:{TEXT};font-size:18px;font-weight:700;margin-bottom:2px">{dt_str}</div>
          <div style="color:{TEXT_DIM};font-size:13px;margin-bottom:6px">{tm_str} · {ago_str}</div>
          {off_badge}
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px">
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Trader</div>
                 <div style="color:{BLUE};font-size:14px;font-weight:600">{row["trader_id"]}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Client</div>
                 <div style="color:{TEXT};font-size:14px;font-weight:600">{row.get("client_id","—")}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Symbol</div>
                 <div style="color:{TEXT};font-size:14px;font-weight:600">{row["symbol"]}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Exchange</div>
                 <div style="color:{TEXT};font-size:14px;font-weight:600">{row["exchange"]}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Side</div>
                 <div style="color:{side_col};font-size:14px;font-weight:700">{str(row["side"]).upper()}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Order type</div>
                 <div style="color:{TEXT};font-size:14px">{str(row.get("order_type","—")).title()}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Volume</div>
                 <div style="color:{TEXT};font-size:14px;font-weight:600">{int(row["volume"]):,}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Price</div>
                 <div style="color:{TEXT};font-size:14px;font-weight:600">${row["price"]:.2f}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Trade value</div>
                 <div style="color:{TEXT};font-size:14px;font-weight:600">{tv_str}</div></div>
            <div><div style="color:{TEXT_DIM};font-size:11px;margin-bottom:2px">Anomaly rank</div>
                 <div style="color:{RED};font-size:14px;font-weight:700">{rank_txt}</div></div>
          </div>
          <div style="margin-top:14px">{rules_html}</div>
          <div style="background:{BG_CARD};border:1px solid {BORDER};border-radius:6px;
                      padding:10px 14px;margin-top:12px">
            <div style="color:{TEXT_DIM};font-size:10px;font-weight:700;letter-spacing:1px;margin-bottom:4px">TOP SHAP SIGNALS</div>
            <div style="color:{TEXT_DIM};font-size:13px">{shap_txt}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    with why_col:
        ev_points  = memo.get("evidence_points", []) if memo else []
        dot_colors = [RED, BLUE, RED, YELLOW, PURPLE, GREEN]
        ev_html    = ""
        for i, pt in enumerate(ev_points[:4]):
            dc = dot_colors[i % len(dot_colors)]
            if " — " in pt:
                bold_part, rest = pt.split(" — ", 1)
                pt_html = f"<b>{bold_part}</b> — {rest}"
            else:
                pt_html = pt
            ev_html += (
                f'<div style="display:flex;gap:10px;margin-bottom:14px">'
                f'<span style="color:{dc};flex-shrink:0;margin-top:2px">●</span>'
                f'<div style="color:{TEXT};font-size:13px;line-height:1.55">{pt_html}</div>'
                f'</div>'
            )
        if not ev_html:
            ev_html = (
                f'<p style="color:{TEXT_DIM};font-style:italic;font-size:13px">'
                f'Run investigation to see detailed analysis.</p>'
            )

        st.markdown(f"""
        <div style="background:{BG_CARD2};border:1px solid {BORDER};border-radius:8px;
                    padding:20px;margin:6px 0 8px">
          <div style="color:{TEXT_DIM};font-size:10px;font-weight:700;letter-spacing:1px;
                      margin-bottom:14px">WHY THIS TRADE IS FLAGGED</div>
          {ev_html}
        </div>
        """, unsafe_allow_html=True)

        if verdict:
            conf     = memo.get("confidence", "HIGH") if memo else "—"
            conf_col = {"HIGH": TEXT, "MEDIUM": YELLOW, "LOW": TEXT_DIM}.get(conf, TEXT_DIM)
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
              <span style="color:{vc};border:1px solid {vc};border-radius:6px;
                           padding:5px 14px;font-size:12px;font-weight:800">{verdict}</span>
              <span style="color:{conf_col};font-size:13px;font-weight:600">{conf} CONFIDENCE</span>
            </div>
            """, unsafe_allow_html=True)
            b1, b2, b3 = st.columns(3)
            b1.button("Full memo", key=f"fm_{row['trade_id']}")
            if b2.button("Investigate", key=f"inv_d_{row['trade_id']}", type="primary"):
                with st.spinner("Running 4 agents..."):
                    result = run_investigation(row["trade_id"])
                if result:
                    st.session_state.setdefault("verdicts", {})[row["trade_id"]] = result.get("verdict", "ERROR")
                    st.session_state.setdefault("memos", {})[row["trade_id"]]    = result.get("compliance_memo", {})
                    st.session_state.setdefault("investigated_today", set()).add(row["trade_id"])
                st.rerun()
            if memo:
                b3.download_button(
                    "↓ PDF", data=json.dumps(memo, indent=2).encode(),
                    file_name=f"memo_{str(row['trade_id'])[:8]}.json",
                    mime="application/json", key=f"pdf_{row['trade_id']}",
                )
        else:
            if st.button("Investigate", key=f"inv_nd_{row['trade_id']}", type="primary"):
                with st.spinner("Running 4 agents..."):
                    result = run_investigation(row["trade_id"])
                if result:
                    st.session_state.setdefault("verdicts", {})[row["trade_id"]] = result.get("verdict", "ERROR")
                    st.session_state.setdefault("memos", {})[row["trade_id"]]    = result.get("compliance_memo", {})
                    st.session_state.setdefault("investigated_today", set()).add(row["trade_id"])
                st.rerun()


# ── Tab 2 — Flagged Trades ──────────────────────────────────────────────────────

def page_flagged_trades(df: pd.DataFrame) -> None:
    verdicts = st.session_state.get("verdicts", {})
    memos    = st.session_state.get("memos", {})
    expanded = st.session_state.get("expanded_trade")

    st.markdown(
        f'<p style="color:{GREEN};font-size:13px;font-weight:600;margin-bottom:12px">'
        f'&#9679; Flagged Trades — details load on click</p>',
        unsafe_allow_html=True,
    )

    flagged_all = df[df["is_anomaly"] == True].copy()

    # ── Search + type filter ──────────────────────────────────────────────────
    s1, s2    = st.columns([5, 2])
    search_q  = s1.text_input("", placeholder="Search traders, symbols, trade IDs...",
                               key="ft_search", label_visibility="collapsed")
    type_filt = s2.selectbox("", ["All types"] + list(TYPE_COLORS.keys()),
                              key="ft_type", label_visibility="collapsed")

    # ── Company pills ─────────────────────────────────────────────────────────
    pill_cols    = st.columns(len(SYMBOLS) + 1)
    pill_options = ["All"] + SYMBOLS
    for i, sym in enumerate(pill_options):
        cnt   = len(flagged_all) if sym == "All" else len(flagged_all[flagged_all["symbol"] == sym])
        label = f"All · {cnt:,}" if sym == "All" else f"{sym} · {cnt:,}"
        is_sel = st.session_state.get("selected_symbol", "All") == sym
        if pill_cols[i].button(label, key=f"ft_pill_{sym}",
                               type="primary" if is_sel else "secondary"):
            st.session_state["selected_symbol"] = sym
            st.session_state["ft_page"] = 1

    # ── Apply filters ─────────────────────────────────────────────────────────
    flagged = flagged_all.copy()
    sel_sym = st.session_state.get("selected_symbol", "All")
    if sel_sym != "All":
        flagged = flagged[flagged["symbol"] == sel_sym]
    if type_filt != "All types":
        flagged = flagged[flagged["anomaly_type"] == type_filt]
    if search_q:
        q = search_q.lower()
        flagged = flagged[
            flagged["trader_id"].str.lower().str.contains(q, na=False)
            | flagged["symbol"].str.lower().str.contains(q, na=False)
            | flagged["trade_id"].str.lower().str.contains(q, na=False)
        ]
    flagged   = flagged.sort_values("anomaly_rank", ascending=True)
    n_flagged = len(flagged)

    st.markdown("<div style='margin:10px 0'></div>", unsafe_allow_html=True)

    # ── Table header ──────────────────────────────────────────────────────────
    COL_W = [0.35, 0.6, 1.1, 1.3, 1.1, 1.0, 0.9, 0.75, 1.0, 0.3]
    h = st.columns(COL_W)
    for col, lbl in zip(h, ["RANK","SYMBOL","TRADE ID","TRADER / CLIENT",
                              "EXECUTED","TYPE","VOL / SIDE","PRICE","SCORE",""]):
        col.markdown(
            f'<span style="color:{TEXT_DIM};font-size:10px;font-weight:700;'
            f'letter-spacing:0.5px;text-transform:uppercase">{lbl}</span>',
            unsafe_allow_html=True,
        )
    st.markdown(f"<hr style='border-color:{BORDER};margin:4px 0 0'>", unsafe_allow_html=True)

    # ── Pagination state ──────────────────────────────────────────────────────
    page_size    = 50
    total_pages  = max(1, (n_flagged + page_size - 1) // page_size)
    current_page = max(1, min(st.session_state.get("ft_page", 1), total_pages))
    start = (current_page - 1) * page_size
    end   = min(start + page_size, n_flagged)

    # ── Rows ──────────────────────────────────────────────────────────────────
    for _, row in flagged.iloc[start:end].iterrows():
        tid     = row["trade_id"]
        verdict = verdicts.get(tid)
        vc      = {"ESCALATE": RED, "MONITOR": YELLOW, "DISMISS": GREEN,
                   "ERROR": TEXT_DIM}.get(verdict, TEXT_DIM)
        tc      = TYPE_COLORS.get(row["anomaly_type"], TEXT_DIM)
        is_exp  = expanded == tid

        r = st.columns(COL_W)
        r[0].markdown(f'<b style="color:{BLUE};font-size:14px">#{int(row["anomaly_rank"])}</b>',
                      unsafe_allow_html=True)
        r[1].markdown(f'<b style="color:{TEXT};font-size:14px">{row["symbol"]}</b>',
                      unsafe_allow_html=True)
        r[2].markdown(
            f'<span style="color:{TEXT_DIM};font-size:12px">{tid[:8]}</span><br>'
            f'<span style="color:{TEXT_DIM};font-size:11px">{row["exchange"]}</span>',
            unsafe_allow_html=True,
        )
        r[3].markdown(
            f'<span style="color:{BLUE};font-size:13px">{row["trader_id"]}</span><br>'
            f'<span style="color:{TEXT_DIM};font-size:11px">{row.get("client_id","")}</span>',
            unsafe_allow_html=True,
        )
        ago     = time_ago(row["timestamp"])
        off_h   = bool(row.get("is_off_hours", False))
        hrs_lbl = (
            f'<span style="color:{YELLOW};font-size:11px">off-hours</span>'
            if off_h else
            f'<span style="color:{TEXT_DIM};font-size:11px">market hours</span>'
        )
        r[4].markdown(
            f'<span style="color:{TEXT_DIM};font-size:12px">{ago}</span><br>{hrs_lbl}',
            unsafe_allow_html=True,
        )
        atype_lbl = str(row["anomaly_type"]).replace("_", " ").upper()
        r[5].markdown(
            f'<span style="background:{tc}22;color:{tc};border:1px solid {tc};'
            f'border-radius:14px;padding:3px 9px;font-size:10px;font-weight:700">'
            f'{atype_lbl}</span>',
            unsafe_allow_html=True,
        )
        side_col = GREEN if str(row["side"]).lower() == "buy" else RED
        r[6].markdown(
            f'<span style="color:{TEXT};font-size:13px">{int(row["volume"]):,}</span><br>'
            f'<span style="color:{side_col};font-size:11px;font-weight:700">'
            f'{str(row["side"]).upper()}</span>',
            unsafe_allow_html=True,
        )
        r[7].markdown(
            f'<span style="color:{TEXT};font-size:13px">${row["price"]:.2f}</span>',
            unsafe_allow_html=True,
        )
        bar_w = min(abs(float(row["anomaly_score"])) / 0.3 * 100, 100)
        r[8].markdown(
            f'<div style="display:flex;align-items:center;gap:6px;padding-top:6px">'
            f'<div style="width:42px;height:4px;background:{BORDER};border-radius:2px">'
            f'<div style="width:{bar_w:.0f}%;height:100%;background:{RED};border-radius:2px">'
            f'</div></div>'
            f'<span style="color:{RED};font-size:11px">{float(row["anomaly_score"]):.3f}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        exp_lbl = "▲" if is_exp else "▼"
        if r[9].button(exp_lbl, key=f"exp_{tid}"):
            st.session_state["expanded_trade"] = None if is_exp else tid

        st.markdown(f"<hr style='border-color:{BORDER};margin:2px 0'>", unsafe_allow_html=True)

        if is_exp:
            _render_trade_detail(row, memos.get(tid, {}), verdict, vc, n_flagged)

    # ── Pagination bar ────────────────────────────────────────────────────────
    st.markdown("<div style='margin:16px 0 4px'></div>", unsafe_allow_html=True)
    pg_l, pg_r = st.columns([3, 4])
    pg_l.markdown(
        f'<span style="color:{TEXT_DIM};font-size:13px">'
        f'Showing {start+1}–{end} of {n_flagged:,} · Page {current_page} of {total_pages}</span>',
        unsafe_allow_html=True,
    )
    with pg_r:
        pb = st.columns(7)
        if pb[0].button("Prev", key="ft_prev", disabled=current_page <= 1):
            st.session_state["ft_page"] = current_page - 1
            st.rerun()
        for idx, pg_n in enumerate([1, 2, 3]):
            if total_pages >= pg_n:
                is_active = current_page == pg_n
                if pb[idx + 1].button(str(pg_n), key=f"ft_pg{pg_n}",
                                      type="primary" if is_active else "secondary"):
                    st.session_state["ft_page"] = pg_n
                    st.rerun()
        pb[4].markdown(
            f'<span style="color:{TEXT_DIM};font-size:18px">···</span>',
            unsafe_allow_html=True,
        )
        if total_pages > 3:
            is_last = current_page == total_pages
            if pb[5].button(str(total_pages), key="ft_pglast",
                            type="primary" if is_last else "secondary"):
                st.session_state["ft_page"] = total_pages
                st.rerun()
        if pb[6].button("Next", key="ft_next", disabled=current_page >= total_pages):
            st.session_state["ft_page"] = current_page + 1
            st.rerun()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="ATS® Trade Surveillance",
        page_icon=":chart_with_upwards_trend:",
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
        "expanded_trade":      None,
        "ft_page":             1,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Load data
    df         = load_trade_summary()
    memos_list = load_memos_list()
    n_flagged  = int(df["is_anomaly"].sum())
    n_memos    = len(memos_list)

    # Fixed top bar (renders over page content via z-index)
    prices = get_live_prices(tuple(SYMBOLS))
    render_top_bar(prices)

    render_market_panel()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Overview",
        f"⚠ Flagged Trades ({n_flagged:,})",
        f"Memos ({n_memos})",
        "Market Context",
    ])

    with tab1:
        page_overview(df, memos_list)

    with tab2:
        page_flagged_trades(df)

    with tab3:
        memos_list = load_memos_list()

        # Filter bar
        fb1, fb2, fb3, fb4, fb5 = st.columns([2, 2, 2, 3, 2])
        v_filter  = fb1.selectbox("VERDICT", ["All verdicts", "ESCALATE", "MONITOR", "DISMISS"], key="r_verdict")
        s_filter  = fb2.selectbox("SYMBOL",  ["All symbols"] + SYMBOLS, key="r_symbol")
        sort_r    = fb3.selectbox("SORT",    ["Newest", "Oldest"], key="r_sort")
        memo_search = fb4.text_input("SEARCH MEMO", placeholder="search summary, evidence...", key="r_search")
        fb5.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        gen_report = fb5.button("Generate Daily Report", key="gen_report", type="primary")

        if not memos_list:
            st.markdown(f'<div style="color:{TEXT_DIM};text-align:center;padding:80px 0;font-size:16px">No investigations yet. Go to Flagged Trades to investigate.</div>', unsafe_allow_html=True)
        else:
            # Load all memos
            all_memos = []
            for m in memos_list:
                memo = st.session_state.get("memos", {}).get(m["trade_id"]) or load_memo(m["trade_id"])
                if memo:
                    all_memos.append({"meta": m, "memo": memo})

            # Apply filters
            if v_filter != "All verdicts":
                all_memos = [m for m in all_memos if m["memo"].get("verdict") == v_filter]
            if s_filter != "All symbols":
                all_memos = [m for m in all_memos if m["meta"].get("symbol","") == s_filter or s_filter in m["memo"].get("summary","")]
            if memo_search:
                q = memo_search.lower()
                all_memos = [m for m in all_memos if q in json.dumps(m["memo"]).lower()]
            if sort_r == "Oldest":
                all_memos = sorted(all_memos, key=lambda x: x["meta"].get("last_modified", ""))
            else:
                all_memos = sorted(all_memos, key=lambda x: x["meta"].get("last_modified", ""), reverse=True)

            st.markdown(f'<p style="color:{TEXT_DIM};font-size:13px;margin-bottom:16px">{len(all_memos)} investigation(s)</p>', unsafe_allow_html=True)

            for item in all_memos:
                memo = item["memo"]
                meta = item["meta"]
                verdict  = memo.get("verdict", "")
                vc = {
                    "ESCALATE": RED, "MONITOR": YELLOW,
                    "DISMISS": GREEN
                }.get(verdict, TEXT_DIM)
                ev_html = "".join([f'<div style="color:{TEXT};padding:2px 0">{i+1}. {p}</div>' for i, p in enumerate(memo.get("evidence_points", []))])
                rule = memo.get("rule_violated", "")

                st.markdown(f"""
                <div style="background:{BG_CARD2};border-left:4px solid {vc};border-radius:8px;padding:20px;margin-bottom:16px">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
                    <div style="display:flex;align-items:center;gap:12px">
                      <span style="background:{vc};color:white;border-radius:12px;padding:3px 12px;font-size:11px;font-weight:800">{verdict}</span>
                      <span style="color:{TEXT};font-weight:700;font-size:15px">{meta.get('symbol','')}</span>
                      <span style="color:{TEXT_DIM};font-size:13px">{meta.get('trade_id','')[:8]}...</span>
                      <span style="color:{TEXT_DIM};font-size:12px">{str(meta.get('last_modified',''))[:16]} UTC</span>
                    </div>
                  </div>
                  <div style="margin-bottom:10px">
                    <div style="color:{TEXT_DIM};font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">SUMMARY</div>
                    <div style="color:{TEXT};font-size:13px">{memo.get('summary','')}</div>
                  </div>
                  <div style="margin-bottom:10px">
                    <div style="color:{TEXT_DIM};font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">EVIDENCE ({len(memo.get('evidence_points',[]))})</div>
                    {ev_html}
                  </div>
                  <div style="margin-bottom:10px">
                    <div style="color:{TEXT_DIM};font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">RULES</div>
                    <span style="background:{vc}22;color:{vc};border:1px solid {vc};border-radius:12px;padding:2px 10px;font-size:11px;font-weight:700">{rule}</span>
                  </div>
                  <div style="margin-bottom:10px">
                    <div style="color:{TEXT_DIM};font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">ACTION</div>
                    <div style="color:{TEXT};font-size:13px">{memo.get('recommended_action','')}</div>
                  </div>
                  <div>
                    <div style="color:{TEXT_DIM};font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">DATA GAPS</div>
                    <div style="color:{TEXT_DIM};font-style:italic;font-size:12px">{memo.get('data_gaps','')}</div>
                  </div>
                </div>""", unsafe_allow_html=True)

                st.download_button(
                    "↓ Download PDF",
                    data=json.dumps(memo, indent=2).encode(),
                    file_name=f"memo_{meta.get('trade_id','')[:8]}.json",
                    mime="application/json",
                    key=f"dl_{meta.get('trade_id','')}"
                )
                st.markdown("<hr style='border-color:#21262d;margin:8px 0'>", unsafe_allow_html=True)

    with tab4:
        flagged = df[df["is_anomaly"] == True].copy()
        prices  = get_live_prices(tuple(SYMBOLS))

        # Company pills
        st.markdown(f'<p style="color:{TEXT_DIM};font-size:11px;font-weight:700;text-transform:uppercase;margin-bottom:8px">COMPANY COVERAGE</p>', unsafe_allow_html=True)
        cp_cols = st.columns(8)
        cp_options = ["All"] + SYMBOLS
        for i, sym in enumerate(cp_options):
            count = len(flagged) if sym == "All" else len(flagged[flagged["symbol"] == sym])
            is_sel = st.session_state.get("mc_symbol", "AAPL") == sym
            if cp_cols[i].button(f"{sym} · {count:,}", key=f"mc_pill_{sym}", type="primary" if is_sel else "secondary"):
                st.session_state["mc_symbol"] = sym

        symbol = st.session_state.get("mc_symbol", "AAPL")
        sym_flagged = flagged[flagged["symbol"] == symbol] if symbol != "All" else flagged
        price_data  = prices.get(symbol, {})
        live_price  = price_data.get("price")
        pct_change  = price_data.get("pct_change")

        # 3 KPI cards
        k1, k2, k3 = st.columns(3)
        price_str  = f"${live_price:.2f}" if live_price else "--"
        change_str = f"{'▲' if (pct_change or 0) >= 0 else '▼'} {abs(pct_change or 0):.2f}% today" if pct_change else ""
        change_col = GREEN if (pct_change or 0) >= 0 else RED

        k1.markdown(f"""
        <div style="background:{BG_CARD};border-radius:8px;padding:20px">
          <div style="color:{TEXT_DIM};font-size:11px;font-weight:700;text-transform:uppercase">{symbol} LIVE PRICE</div>
          <div style="color:{RED};font-size:32px;font-weight:800;margin:8px 0">{price_str}</div>
          <div style="color:{change_col};font-size:13px">{change_str}</div>
        </div>""", unsafe_allow_html=True)

        k2.markdown(f"""
        <div style="background:{BG_CARD};border-radius:8px;padding:20px">
          <div style="color:{TEXT_DIM};font-size:11px;font-weight:700;text-transform:uppercase">ANOMALIES FOR {symbol}</div>
          <div style="color:{RED};font-size:32px;font-weight:800;margin:8px 0">{len(sym_flagged):,}</div>
        </div>""", unsafe_allow_html=True)

        pct = len(sym_flagged) / max(len(flagged), 1) * 100
        k3.markdown(f"""
        <div style="background:{BG_CARD};border-radius:8px;padding:20px">
          <div style="color:{TEXT_DIM};font-size:11px;font-weight:700;text-transform:uppercase">SHARE OF ALL ANOMALIES</div>
          <div style="color:{YELLOW};font-size:32px;font-weight:800;margin:8px 0">{pct:.1f}%</div>
        </div>""", unsafe_allow_html=True)

        st.markdown("<div style='margin:16px 0'></div>", unsafe_allow_html=True)

        # Price chart
        if symbol != "All":
            history = get_stock_history(symbol, "1mo")
            if not history.empty:
                st.markdown(f'<p style="color:{TEXT};font-size:15px;font-weight:700">{symbol} — 1 Month Price</p>', unsafe_allow_html=True)
                fig_price = go.Figure()
                fig_price.add_trace(go.Scatter(
                    x=history.index, y=history["Close"],
                    fill="tozeroy",
                    line=dict(color=BLUE, width=2),
                    fillcolor="rgba(88,166,255,0.1)",
                    hovertemplate="<b>%{x}</b><br>price : %{y:.2f}<extra></extra>"
                ))
                fig_price.update_layout(**PLOTLY_LAYOUT, height=300)
                st.plotly_chart(fig_price, use_container_width=True)

                # Volume chart
                st.markdown(f'<p style="color:{TEXT};font-size:15px;font-weight:700">Trading Volume</p>', unsafe_allow_html=True)
                fig_vol = go.Figure()
                fig_vol.add_trace(go.Bar(
                    x=history.index, y=history["Volume"],
                    marker_color=TEXT_DIM,
                    hovertemplate="<b>%{x}</b><br>volume: %{y:,}<extra></extra>"
                ))
                fig_vol.update_layout(**PLOTLY_LAYOUT, height=200)
                st.plotly_chart(fig_vol, use_container_width=True)

        # Anomaly timeline
        if not sym_flagged.empty:
            st.markdown(f'<p style="color:{TEXT};font-size:15px;font-weight:700">Anomaly Events Timeline</p>', unsafe_allow_html=True)
            fig_scatter = px.scatter(
                sym_flagged, x="timestamp", y="anomaly_score",
                color="anomaly_type",
                color_discrete_map=TYPE_COLORS,
                hover_data=["trader_id", "trade_id", "anomaly_type"],
                height=300
            )
            fig_scatter.update_layout(**PLOTLY_LAYOUT)
            st.plotly_chart(fig_scatter, use_container_width=True)

        # Two tables
        t1, t2 = st.columns(2)
        with t1:
            st.markdown(f'<p style="color:{TEXT};font-size:14px;font-weight:700">Top Flagged Traders</p>', unsafe_allow_html=True)
            if not sym_flagged.empty:
                top_traders = sym_flagged.groupby("trader_id").size().reset_index(name="count").sort_values("count", ascending=False).head(10)
                top_traders.index = range(1, len(top_traders)+1)
                st.dataframe(top_traders, use_container_width=True)

        with t2:
            st.markdown(f'<p style="color:{TEXT};font-size:14px;font-weight:700">Worst Anomalies</p>', unsafe_allow_html=True)
            if not sym_flagged.empty:
                worst = sym_flagged.sort_values("anomaly_rank").head(10)[
                    ["anomaly_rank","timestamp","anomaly_type","anomaly_score","trader_id"]
                ].copy()
                worst.index = range(1, len(worst)+1)
                st.dataframe(worst, use_container_width=True)

        # Heatmap
        if not sym_flagged.empty:
            st.markdown(f'<p style="color:{TEXT};font-size:15px;font-weight:700">When Do Violations Occur?</p>', unsafe_allow_html=True)
            h_df = sym_flagged.copy()
            h_df["hour"] = pd.to_datetime(h_df["timestamp"]).dt.hour
            h_df["day"]  = pd.to_datetime(h_df["timestamp"]).dt.day_name()
            heat = h_df.groupby(["day","hour"]).size().reset_index(name="count")
            day_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
            fig_heat = go.Figure(go.Heatmap(
                x=heat["hour"], y=heat["day"],
                z=heat["count"],
                colorscale="Reds",
                hovertemplate="Hour: %{x}<br>Day: %{y}<br>Count: %{z}<extra></extra>"
            ))
            fig_heat.update_layout(**PLOTLY_LAYOUT, height=300,
                yaxis=dict(categoryorder="array", categoryarray=day_order))
            st.plotly_chart(fig_heat, use_container_width=True)

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
