"""Command-line entry point for the country-search-volumes ETL."""

from __future__ import annotations

import argparse
import logging
from typing import Sequence

from google_trends_etl.config import ConfigError, Settings, load_settings
from google_trends_etl.db import connect
from google_trends_etl.extract_country_search_volumes import extract_country_interest
from google_trends_etl.load_country_search_volumes import upsert_country_volumes
from google_trends_etl.migrate import apply_migrations
from google_trends_etl.transform_country_search_volumes import transform_country_volumes

LOGGER = logging.getLogger(__name__)


def run(
    *,
    settings: Settings | None = None,
    skip_migrations: bool = False,
) -> int:
    settings = settings or load_settings()
    if not settings.search_terms:
        raise ConfigError("SEARCH_TERMS must list at least one comma-separated term.")

    with connect(settings) as conn:
        if not skip_migrations:
            apply_migrations(conn, local_tz=settings.trends_timezone)

        extracted = extract_country_interest(
            settings.search_terms,
            settings.reference_term,
        )
        records = transform_country_volumes(
            extracted,
            reference_volume=settings.reference_term_daily_volume,
            local_tz=settings.trends_timezone,
        )

        if not records:
            LOGGER.warning("No country volume rows produced for %s term(s).",
                           len(settings.search_terms))

        rows_upserted = upsert_country_volumes(conn, records)
        LOGGER.info("Upserted %s country volume row(s).", rows_upserted)
        return rows_upserted


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the country-search-volumes ETL.")
    parser.add_argument("--skip-migrations", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    try:
        run(skip_migrations=args.skip_migrations)
    except ConfigError as exc:
        parser.error(str(exc))
    except Exception:
        LOGGER.exception("Country-search-volumes ETL failed.")
        return 1

    return 0


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    raise SystemExit(main())
