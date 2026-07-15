import unittest
from datetime import timezone
from unittest.mock import patch

from google_trends_etl import main as top_trends_main
from google_trends_etl.config import GoogleTrendsSettings, Settings


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class TopTrendsMainTests(unittest.TestCase):
    def test_run_logs_step_timings(self):
        settings = _settings()

        with (
            patch("google_trends_etl.main.connect", return_value=_Connection()),
            patch("google_trends_etl.main.apply_migrations"),
            patch("google_trends_etl.main.extract_trends", return_value=[{"term": "ai"}]),
            patch("google_trends_etl.main.transform_trends", return_value=[object()]),
            patch("google_trends_etl.main.insert_records", return_value=1),
            patch("google_trends_etl.main.record_rows_affected"),
            patch("google_trends_etl.main.time.sleep"),
            self.assertLogs("google_trends_etl.main", level="INFO") as logs,
        ):
            rows_inserted = top_trends_main.run(settings=settings)

        self.assertEqual(rows_inserted, 1)
        output = "\n".join(logs.output)
        self.assertIn("Step database connect completed in", output)
        self.assertIn("Step migrations completed in", output)
        self.assertIn("Step extract completed in", output)
        self.assertIn("Step transform completed in", output)
        self.assertIn("Step pre-load sleep completed in", output)
        self.assertIn("Step load completed in", output)
        self.assertIn("Step telemetry completed in", output)
        self.assertIn("Google Trends ETL completed in", output)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://example",
        pg_params={},
        trends_geo="US",
        trends_top_n=1,
        trends_timezone=timezone.utc,
        pre_load_sleep_seconds=0.01,
        search_terms=(),
        reference_term="google",
        reference_term_daily_volume=300000000,
        country_volume_weight_overrides={},
        country_volume_unknown_weight=0,
        google_trends=GoogleTrendsSettings(
            request_delay_seconds=0,
            max_retries=1,
            retry_backoff_seconds=0,
            retry_backoff_multiplier=1,
        ),
    )


if __name__ == "__main__":
    unittest.main()
