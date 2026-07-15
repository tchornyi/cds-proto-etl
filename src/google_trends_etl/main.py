"""Command-line entry point for the Google Trends ETL."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import logging
import time
from typing import Sequence

from google_trends_etl.config import ConfigError, Settings, load_settings
from google_trends_etl.db import connect
from google_trends_etl.extract import extract_trends
from google_trends_etl.load import insert_records
from google_trends_etl.migrate import apply_migrations
from google_trends_etl.telemetry import record_rows_affected
from google_trends_etl.transform import transform_trends

LOGGER = logging.getLogger(__name__)


def run(
    *,
    settings: Settings | None = None,
    skip_migrations: bool = False,
    geo: str | None = None,
) -> int:
    settings = settings or load_settings(geo_override=geo)
    run_started_at = time.perf_counter()

    with _timed_step("database connect"):
        conn_context = connect(settings)

    with conn_context as conn:
        if not skip_migrations:
            with _timed_step("migrations"):
                apply_migrations(conn, local_tz=settings.trends_timezone)
        else:
            LOGGER.info("Step migrations skipped.")

        with _timed_step("extract"):
            raw_entries = extract_trends(
                settings.trends_geo,
                trends_settings=settings.google_trends,
            )

        with _timed_step("transform"):
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
            with _timed_step("pre-load sleep"):
                LOGGER.info(
                    "Sleeping %.2f second(s) before load.",
                    settings.pre_load_sleep_seconds,
                )
                time.sleep(settings.pre_load_sleep_seconds)

        with _timed_step("load"):
            rows_inserted = insert_records(conn, records)

        with _timed_step("telemetry"):
            record_rows_affected(
                rows_inserted,
                pipeline="current_trends",
                table="current_trends",
                operation="upsert",
            )
        LOGGER.info("Inserted %s current trend row(s).", rows_inserted)
        LOGGER.info(
            "Google Trends ETL completed in %.3f second(s).",
            time.perf_counter() - run_started_at,
        )
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


@contextmanager
def _timed_step(name: str) -> Iterator[None]:
    started_at = time.perf_counter()
    try:
        yield
    except Exception:
        LOGGER.info(
            "Step %s failed after %.3f second(s).",
            name,
            time.perf_counter() - started_at,
        )
        raise
    else:
        LOGGER.info(
            "Step %s completed in %.3f second(s).",
            name,
            time.perf_counter() - started_at,
        )


if __name__ == "__main__":
    raise SystemExit(main())
