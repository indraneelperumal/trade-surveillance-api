import time

import yfinance as yf
from fastapi import APIRouter

router = APIRouter()

SYMBOLS = [
    "AAPL", "MSFT", "TSLA", "AMZN", "NVDA",
    "GOOGL", "META", "JPM", "GS", "BAC",
    "XOM", "JNJ", "QQQ", "SPY",
]

# (data, fetched_at) — refreshed at most once per TTL seconds per process
_cache: tuple[list[dict], float] | None = None
_CACHE_TTL = 60.0


@router.get("/market/prices")
def get_market_prices() -> list[dict]:
    global _cache
    now = time.time()
    if _cache is not None and (now - _cache[1]) < _CACHE_TTL:
        return _cache[0]

    result: list[dict] = []
    try:
        tickers = yf.Tickers(" ".join(SYMBOLS))
        for symbol in SYMBOLS:
            try:
                fi = tickers.tickers[symbol].fast_info
                price: float = fi.last_price
                prev: float = fi.previous_close
                change = (price - prev) if (price and prev) else 0.0
                change_pct = (change / prev * 100) if prev else 0.0
                result.append({
                    "symbol": symbol,
                    "price": round(price, 2) if price else None,
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 3),
                })
            except Exception:
                result.append({
                    "symbol": symbol,
                    "price": None,
                    "change": 0.0,
                    "change_pct": 0.0,
                })
    except Exception:
        return []

    _cache = (result, now)
    return result
