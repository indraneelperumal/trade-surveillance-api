"""
Live trade simulator — reuses :mod:`mock_data_script` (same row shape, GBM state, anomalies).

Use **after** a one-time backfill from ``mock_data_script.py`` (same ``DATABASE_URL``).

Examples::

    cd trade-surveillance-api && source .venv/bin/activate
    python live_simulate.py --batch-size 75
    python live_simulate.py --batch-size 50 --max-age-sec 15 --interval-sec 180

Cron (Render): same env as API, schedule every few minutes, command::

    python live_simulate.py --batch-size 75
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import mock_data_script as md
from trade_surveillance.db.migrator import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def _insert_batch(batch_size: int, rng: random.Random, max_age_sec: int) -> int:
    engine = get_engine()
    anchor = datetime.now(timezone.utc)
    rows: list[dict] = []
    for _ in range(batch_size):
        micro = anchor - timedelta(
            seconds=rng.randint(0, max_age_sec),
            microseconds=rng.randint(0, 999_999),
        )
        rows.append(md.gen_trade(timestamp_override=micro))
    with engine.begin() as conn:
        md._seed_reference_tables(conn)
        conn.execute(md._TRADES_INSERT_SQL, rows)
    logging.info("Inserted %s trades near %s", batch_size, anchor.isoformat())
    return batch_size


def main() -> int:
    p = argparse.ArgumentParser(description="Insert a batch of trades near current time (live demo).")
    p.add_argument("--batch-size", type=int, default=75, help="Trades per tick")
    p.add_argument(
        "--max-age-sec",
        type=int,
        default=8,
        help="Spread timestamps within this many seconds before anchor (default 8)",
    )
    p.add_argument(
        "--interval-sec",
        type=int,
        default=0,
        help="Sleep between ticks; 0 = run once (Cron-friendly)",
    )
    p.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducible jitter")
    args = p.parse_args()
    if args.batch_size < 1:
        print("--batch-size must be >= 1", file=sys.stderr)
        return 1
    if args.max_age_sec < 0:
        print("--max-age-sec must be >= 0", file=sys.stderr)
        return 1

    rng = random.Random(args.seed if args.seed is not None else int(time.time() * 1e6) % (2**31))

    _insert_batch(args.batch_size, rng, args.max_age_sec)
    while args.interval_sec > 0:
        time.sleep(args.interval_sec)
        _insert_batch(args.batch_size, rng, args.max_age_sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
