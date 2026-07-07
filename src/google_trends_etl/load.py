"""Load transformed trend records into PostgreSQL."""

from __future__ import annotations

from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb

from google_trends_etl.transform import TrendRecord

# One row per (term, trend_date): a term seen again on the same UTC day
# refreshes the existing row; the first appearance on a new day inserts a
# fresh one, preserving per-day trend history.
INSERT_SQL = """
INSERT INTO current_trends (
    snapshot_id,
    snapshot_at,
    trend_date,
    rank,
    term,
    search_volume,
    volume_growth_pct,
    trend_started_at,
    related_queries
) VALUES (
    %(snapshot_id)s,
    %(snapshot_at)s,
    %(trend_date)s,
    %(rank)s,
    %(term)s,
    %(search_volume)s,
    %(volume_growth_pct)s,
    %(trend_started_at)s,
    %(related_queries)s
)
ON CONFLICT (term, trend_date) DO UPDATE SET
    snapshot_id = EXCLUDED.snapshot_id,
    snapshot_at = EXCLUDED.snapshot_at,
    rank = EXCLUDED.rank,
    search_volume = EXCLUDED.search_volume,
    volume_growth_pct = EXCLUDED.volume_growth_pct,
    trend_started_at = COALESCE(EXCLUDED.trend_started_at, current_trends.trend_started_at),
    related_queries = EXCLUDED.related_queries
"""


def insert_records(conn: psycopg.Connection[Any], records: Iterable[TrendRecord]) -> int:
    batch = list(records)
    if not batch:
        return 0

    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, [_as_params(record) for record in batch])
    return len(batch)


def _as_params(record: TrendRecord) -> dict[str, Any]:
    related_queries = (
        Jsonb(record.related_queries) if record.related_queries is not None else None
    )
    return {
        "snapshot_id": record.snapshot_id,
        "snapshot_at": record.snapshot_at,
        "trend_date": record.trend_date,
        "rank": record.rank,
        "term": record.term,
        "search_volume": record.search_volume,
        "volume_growth_pct": record.volume_growth_pct,
        "trend_started_at": record.trend_started_at,
        "related_queries": related_queries,
    }
