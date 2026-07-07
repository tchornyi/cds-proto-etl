from datetime import datetime
import unittest

import pandas as pd

from google_trends_etl.extract_country_search_volumes import (
    CountryExtract,
    CountryInterest,
    InterestBatch as CountryInterestBatch,
)
from google_trends_etl.extract_search_volumes import InterestBatch
from google_trends_etl.transform_country_search_volumes import transform_country_volumes
from google_trends_etl.transform_search_volumes import transform_search_volumes


class SearchVolumeTransformTests(unittest.TestCase):
    def test_search_volumes_scale_against_reference_term(self):
        frame = pd.DataFrame({"alpha": [50, 100], "google": [100, 100]})

        records = transform_search_volumes(
            [InterestBatch(("alpha",), "google", frame)],
            reference_volume=1_000,
            snapshot_at=datetime(2026, 7, 7, 12, 0, 0),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].term, "alpha")
        self.assertEqual(records[0].search_volume, 750)
        self.assertIsNotNone(records[0].snapshot_at.tzinfo)

    def test_country_volumes_distribute_global_volume_by_country_interest(self):
        trend_frame = pd.DataFrame({"alpha": [50, 100], "google": [100, 100]})
        country_frame = pd.DataFrame(
            {
                "geoName": ["United States", "Canada"],
                "geoCode": ["US", "CA"],
                "alpha": [75, 25],
            }
        )
        extracted = CountryExtract(
            interest_batches=(
                CountryInterestBatch(("alpha",), "google", trend_frame),
            ),
            country_interest=(CountryInterest("alpha", country_frame),),
        )

        records = transform_country_volumes(
            extracted,
            reference_volume=1_000,
            snapshot_at=datetime(2026, 7, 7, 12, 0, 0),
        )

        self.assertEqual(
            {(record.country_code, record.search_volume) for record in records},
            {("US", 562), ("CA", 188)},
        )
        self.assertEqual(sum(record.search_volume for record in records), 750)
        self.assertTrue(
            all(record.volume_date.isoformat() == "2026-07-07" for record in records)
        )


if __name__ == "__main__":
    unittest.main()