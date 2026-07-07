"""Load country search volume records into PostgreSQL."""

from __future__ import annotations

from typing import Any, Iterable

import psycopg

from google_trends_etl.transform_country_search_volumes import CountryVolumeRecord

# One row per (term, country_code, volume_date): a country seen again on the
# same local day refreshes that day's row; a new day inserts a fresh one.
INSERT_SQL = """
INSERT INTO country_search_volumes (
    term,
    country_code,
    country_name,
    volume_date,
    search_volume,
    interest,
    snapshot_id,
    snapshot_at
) VALUES (
    %(term)s,
    %(country_code)s,
    %(country_name)s,
    %(volume_date)s,
    %(search_volume)s,
    %(interest)s,
    %(snapshot_id)s,
    %(snapshot_at)s
)
ON CONFLICT (term, country_code, volume_date) DO UPDATE SET
    search_volume = EXCLUDED.search_volume,
    interest = EXCLUDED.interest,
    country_name = COALESCE(EXCLUDED.country_name, country_search_volumes.country_name),
    snapshot_id = EXCLUDED.snapshot_id,
    snapshot_at = EXCLUDED.snapshot_at
"""


def upsert_country_volumes(
    conn: psycopg.Connection[Any],
    records: Iterable[CountryVolumeRecord],
) -> int:
    batch = list(records)
    if not batch:
        return 0

    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, [_as_params(record) for record in batch])
    return len(batch)


def _as_params(record: CountryVolumeRecord) -> dict[str, Any]:
    return {
        "term": record.term,
        "country_code": record.country_code,
        "country_name": record.country_name,
        "volume_date": record.volume_date,
        "search_volume": record.search_volume,
        "interest": record.interest,
        "snapshot_id": record.snapshot_id,
        "snapshot_at": record.snapshot_at,
    }
