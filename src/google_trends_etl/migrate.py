"""Forward-only SQL migration runner."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import psycopg

from google_trends_etl.config import ConfigError, load_settings
from google_trends_etl.db import connect

LOGGER = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def apply_migrations(
    conn: psycopg.Connection[Any],
    *,
    migrations_dir: Path = MIGRATIONS_DIR,
    local_tz: tzinfo | None = None,
) -> list[str]:
    migration_files = sorted(migrations_dir.glob("*.sql"))
    applied_now: list[str] = []

    with conn.transaction():
        # Migrations that cast timestamptz to date (e.g. 003) must land on the
        # configured local day. set_config(..., true) is transaction-local, so
        # the session default returns after commit.
        conn.execute(
            "SELECT set_config('TimeZone', %s, true)",
            (_postgres_timezone(local_tz),),
        )
        conn.execute(SCHEMA_MIGRATIONS_SQL)
        applied = {
            row[0]
            for row in conn.execute("SELECT filename FROM schema_migrations")
        }

        for path in migration_files:
            if path.name in applied:
                continue
            LOGGER.info("Applying migration %s.", path.name)
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (path.name,),
            )
            applied_now.append(path.name)

    if applied_now:
        LOGGER.info("Applied %s migration(s).", len(applied_now))
    else:
        LOGGER.info("No pending migrations.")
    return applied_now


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply pending Google Trends ETL migrations.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    try:
        settings = load_settings()
    except ConfigError as exc:
        parser.error(str(exc))

    with connect(settings) as conn:
        apply_migrations(conn, local_tz=settings.trends_timezone)
    return 0


def _postgres_timezone(local_tz: tzinfo | None) -> str:
    if isinstance(local_tz, ZoneInfo):
        return local_tz.key
    if local_tz is None:
        local_tz = datetime.now().astimezone().tzinfo
    offset = datetime.now(local_tz).utcoffset() or timedelta(0)
    minutes = round(offset.total_seconds() / 60)
    LOGGER.warning(
        "TRENDS_TIMEZONE is not set; using fixed offset UTC%+d:%02d for "
        "migration date bucketing. Set an IANA timezone for DST-correct history.",
        minutes // 60 if minutes >= 0 else -(-minutes // 60),
        abs(minutes) % 60,
    )
    # POSIX zone syntax inverts the sign: local UTC+3 is written "UTC-3".
    sign = "-" if minutes >= 0 else "+"
    hours, remainder = divmod(abs(minutes), 60)
    suffix = f"{hours}" + (f":{remainder:02d}" if remainder else "")
    return f"UTC{sign}{suffix}"


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    raise SystemExit(main())
