"""Load search volume records into PostgreSQL."""

from __future__ import annotations

from typing import Any, Iterable

import psycopg

from google_trends_etl.transform_search_volumes import SearchVolumeRecord

INSERT_SQL = """
INSERT INTO search_volumes (
    snapshot_id,
    snapshot_at,
    term,
    search_volume,
    interest_avg,
    reference_term,
    reference_volume
) VALUES (
    %(snapshot_id)s,
    %(snapshot_at)s,
    %(term)s,
    %(search_volume)s,
    %(interest_avg)s,
    %(reference_term)s,
    %(reference_volume)s
)
"""


def insert_search_volumes(
    conn: psycopg.Connection[Any],
    records: Iterable[SearchVolumeRecord],
) -> int:
    batch = list(records)
    if not batch:
        return 0

    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, [_as_params(record) for record in batch])
    return len(batch)


def _as_params(record: SearchVolumeRecord) -> dict[str, Any]:
    return {
        "snapshot_id": record.snapshot_id,
        "snapshot_at": record.snapshot_at,
        "term": record.term,
        "search_volume": record.search_volume,
        "interest_avg": record.interest_avg,
        "reference_term": record.reference_term,
        "reference_volume": record.reference_volume,
    }
