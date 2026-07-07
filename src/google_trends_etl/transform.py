"""Transform raw Google Trends entries into database-ready records."""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import Any
from uuid import UUID, uuid4

LOGGER = logging.getLogger(__name__)

_MISSING = object()

TERM_FIELDS = ("term", "keyword", "query", "title", "name", "search_term")
VOLUME_FIELDS = (
    "search_volume",
    "searchVolume",
    "traffic",
    "formatted_traffic",
    "formattedTraffic",
    "volume",
    "approx_search_volume",
)
GROWTH_FIELDS = (
    "volume_growth_pct",
    "volumeGrowthPct",
    "growth_pct",
    "growthPercent",
    "percent_increase",
    "increase_percentage",
    "trafficGrowth",
)
STARTED_FIELDS = (
    "trend_started_at",
    "started_at",
    "startedTimestamp",
    "started_timestamp",
    "start_time",
    "startTime",
)
RELATED_FIELDS = (
    "related_queries",
    "relatedQueries",
    "related_keywords",
    "relatedKeywords",
    "trend_keywords",
    "trendKeywords",
    "topics",
    "queries",
)


class TransformError(ValueError):
    """Raised when a raw entry cannot be transformed into a trend record."""


@dataclass(frozen=True)
class TrendRecord:
    snapshot_id: UUID
    snapshot_at: datetime
    trend_date: date
    rank: int
    term: str
    search_volume: int
    volume_growth_pct: int | None
    trend_started_at: datetime | None
    related_queries: Any | None


def transform_trends(
    raw_entries: Iterable[Any],
    *,
    top_n: int = 25,
    snapshot_id: UUID | None = None,
    snapshot_at: datetime | None = None,
    local_tz: tzinfo | None = None,
) -> list[TrendRecord]:
    snapshot_id = snapshot_id or uuid4()
    snapshot_at = _make_aware(snapshot_at or datetime.now(UTC))

    records: list[TrendRecord] = []
    seen_terms: set[str] = set()
    for rank, entry in enumerate(list(raw_entries)[:top_n], start=1):
        try:
            record = transform_entry(
                entry,
                rank=rank,
                snapshot_id=snapshot_id,
                snapshot_at=snapshot_at,
                local_tz=local_tz,
            )
        except TransformError:
            LOGGER.exception("Skipping trend entry at rank %s.", rank)
            continue

        # The load upsert conflicts on (term, trend_date); a term repeated in
        # one batch would make ON CONFLICT hit the same row twice, which
        # PostgreSQL rejects. Keep the best-ranked occurrence.
        if record.term in seen_terms:
            LOGGER.warning("Skipping duplicate term %r at rank %s.", record.term, rank)
            continue
        seen_terms.add(record.term)
        records.append(record)

    return records


def transform_entry(
    entry: Any,
    *,
    rank: int,
    snapshot_id: UUID,
    snapshot_at: datetime,
    local_tz: tzinfo | None = None,
) -> TrendRecord:
    if not 1 <= rank <= 25:
        raise TransformError(f"Rank must be between 1 and 25, got {rank}.")

    term = _parse_term(_first_present(entry, TERM_FIELDS))
    search_volume = _parse_search_volume(_first_present(entry, VOLUME_FIELDS))
    volume_growth_pct = _parse_growth_pct(_first_present(entry, GROWTH_FIELDS, default=None))
    trend_started_at = _parse_optional_datetime(_first_present(entry, STARTED_FIELDS, default=None))
    related_queries = _parse_related_queries(_first_present(entry, RELATED_FIELDS, default=None))

    snapshot_at = _make_aware(snapshot_at)
    return TrendRecord(
        snapshot_id=snapshot_id,
        snapshot_at=snapshot_at,
        trend_date=_local_date(snapshot_at, local_tz),
        rank=rank,
        term=term,
        search_volume=search_volume,
        volume_growth_pct=volume_growth_pct,
        trend_started_at=trend_started_at,
        related_queries=related_queries,
    )


def _first_present(entry: Any, names: Sequence[str], *, default: Any = _MISSING) -> Any:
    for name in names:
        value = _get_value(entry, name)
        if value is not _MISSING:
            return value
    if default is not _MISSING:
        return default
    raise TransformError(f"Missing required field; tried: {', '.join(names)}.")


def _get_value(entry: Any, name: str) -> Any:
    if isinstance(entry, Mapping):
        if name in entry:
            return entry[name]
        normalized = {str(key).lower(): key for key in entry.keys()}
        key = normalized.get(name.lower())
        if key is not None:
            return entry[key]

    if hasattr(entry, name):
        return getattr(entry, name)

    return _MISSING


def _parse_term(value: Any) -> str:
    if value in (None, ""):
        raise TransformError("Trend term is missing.")
    term = str(value).strip()
    if not term:
        raise TransformError("Trend term is empty.")
    return term


def _parse_search_volume(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise TransformError("Search volume is missing.")
    if isinstance(value, int):
        if value < 0:
            raise TransformError(f"Search volume must be non-negative, got {value}.")
        return value
    if isinstance(value, float):
        if value < 0:
            raise TransformError(f"Search volume must be non-negative, got {value}.")
        return int(value)

    text = str(value).strip().replace(",", "")
    match = re.search(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<suffix>[kKmMbB]?)", text)
    if not match:
        raise TransformError(f"Could not parse search volume from {value!r}.")

    number = float(match.group("number"))
    suffix = match.group("suffix").lower()
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
    parsed = int(number * multiplier)
    if parsed < 0:
        raise TransformError(f"Search volume must be non-negative, got {parsed}.")
    return parsed


def _parse_growth_pct(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).strip().replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return int(float(match.group(0)))


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return None
        return _parse_optional_datetime(value[0])
    if isinstance(value, datetime):
        return _make_aware(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds = seconds / 1000
        return datetime.fromtimestamp(seconds, tz=UTC)

    text = str(value).strip()
    numeric = re.fullmatch(r"\d+(?:\.\d+)?", text)
    if numeric:
        return _parse_optional_datetime(float(text))

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return _make_aware(datetime.fromisoformat(text))
    except ValueError:
        raise TransformError(f"Could not parse trend start time from {value!r}.")


def _local_date(snapshot_at: datetime, local_tz: tzinfo | None) -> date:
    # trend_date buckets rows into local calendar days; snapshot_at itself
    # stays UTC. No tz configured -> the system's local timezone.
    if local_tz is None:
        return snapshot_at.astimezone().date()
    return snapshot_at.astimezone(local_tz).date()


def _make_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_related_queries(value: Any) -> Any | None:
    if value in (None, "", []):
        return None
    return _to_plain(value)


def _to_plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _to_plain(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return _make_aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Sequence):
        return [_to_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            key: _to_plain(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)
