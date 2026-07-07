"""Command-line entry point for the Google Trends ETL."""

from __future__ import annotations

import argparse
import logging
import time
from typing import Sequence

from google_trends_etl.config import ConfigError, Settings, load_settings
from google_trends_etl.db import connect
from google_trends_etl.extract import extract_trends
from google_trends_etl.load import insert_records
from google_trends_etl.migrate import apply_migrations
from google_trends_etl.transform import transform_trends

LOGGER = logging.getLogger(__name__)


def run(
    *,
    settings: Settings | None = None,
    skip_migrations: bool = False,
    geo: str | None = None,
) -> int:
    settings = settings or load_settings(geo_override=geo)

    with connect(settings) as conn:
        if not skip_migrations:
            apply_migrations(conn, local_tz=settings.trends_timezone)

        raw_entries = extract_trends(settings.trends_geo)
        records = transform_trends(
            raw_entries,
            top_n=settings.trends_top_n,
            local_tz=settings.trends_timezone,
        )

        if len(records) < settings.trends_top_n:
            LOGGER.warning(
                "Snapshot contains %s row(s), fewer than configured top N of %s.",
                len(records),
                settings.trends_top_n,
            )

        if settings.pre_load_sleep_seconds:
            LOGGER.info(
                "Sleeping %.2f second(s) before load.",
                settings.pre_load_sleep_seconds,
            )
            time.sleep(settings.pre_load_sleep_seconds)

        rows_inserted = insert_records(conn, records)
        LOGGER.info("Inserted %s current trend row(s).", rows_inserted)
        return rows_inserted


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Google Trends ETL.")
    parser.add_argument("--skip-migrations", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--geo", help="Override TRENDS_GEO for this run.")
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    try:
        run(skip_migrations=args.skip_migrations, geo=args.geo)
    except ConfigError as exc:
        parser.error(str(exc))
    except Exception:
        LOGGER.exception("Google Trends ETL failed.")
        return 1

    return 0


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    raise SystemExit(main())
