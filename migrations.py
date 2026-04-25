"""Simple migration runner with no versioning."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from trade_surveillance.db.migrator import create_tables_and_migrate, get_engine
from trade_surveillance.models import create_tables


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Simple migration runner")
    parser.add_argument(
        "command",
        nargs="?",
        default="migrate",
        choices=["create_tables", "migrate", "all"],
        help="create_tables: create from models, migrate: create tables then run migration functions, all: same as migrate",
    )
    args = parser.parse_args()

    try:
        engine = get_engine()
        if args.command == "create_tables":
            # Explicit create-only command
            create_tables(engine)
            print("Tables created from models.")
            return 0
        if args.command in {"migrate", "all"}:
            create_tables_and_migrate()
            print("Tables created and migrations completed.")
            return 0
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
