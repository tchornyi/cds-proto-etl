"""Transform interest batches into approximate absolute search volumes."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable
from uuid import UUID, uuid4

from google_trends_etl.extract_search_volumes import InterestBatch

LOGGER = logging.getLogger(__name__)


class TransformError(ValueError):
    """Raised when an interest batch or term cannot be transformed."""


@dataclass(frozen=True)
class SearchVolumeRecord:
    snapshot_id: UUID
    snapshot_at: datetime
    term: str
    search_volume: int
    interest_avg: float
    reference_term: str
    reference_volume: int


def transform_search_volumes(
    batches: Iterable[InterestBatch],
    *,
    reference_volume: int,
    snapshot_id: UUID | None = None,
    snapshot_at: datetime | None = None,
) -> list[SearchVolumeRecord]:
    snapshot_id = snapshot_id or uuid4()
    snapshot_at = _make_aware(snapshot_at or datetime.now(UTC))

    records: list[SearchVolumeRecord] = []
    seen_terms: set[str] = set()
    for batch in batches:
        try:
            reference_interest = _mean_interest(batch.frame, batch.reference_term)
        except TransformError:
            LOGGER.exception(
                "Skipping batch %s: reference term %r has no usable interest data.",
                batch.terms,
                batch.reference_term,
            )
            continue
        if reference_interest <= 0:
            LOGGER.warning(
                "Skipping batch %s: reference term %r registered zero interest, "
                "cannot calibrate volumes.",
                batch.terms,
                batch.reference_term,
            )
            continue

        for term in batch.terms:
            if term in seen_terms:
                continue
            try:
                interest_avg = _mean_interest(batch.frame, term)
            except TransformError:
                LOGGER.exception("Skipping term %r.", term)
                continue

            # volume(term) ~= interest(term) / interest(reference) * known
            # reference volume — Google normalises keywords within one request,
            # so the ratio is meaningful. An approximation, never exact.
            search_volume = int(round(interest_avg / reference_interest * reference_volume))
            seen_terms.add(term)
            records.append(
                SearchVolumeRecord(
                    snapshot_id=snapshot_id,
                    snapshot_at=snapshot_at,
                    term=term,
                    search_volume=search_volume,
                    interest_avg=interest_avg,
                    reference_term=batch.reference_term,
                    reference_volume=reference_volume,
                )
            )

    return records


def _mean_interest(frame: Any, keyword: str) -> float:
    column = _column_for(frame, keyword)
    try:
        value = float(frame[column].mean())
    except (TypeError, ValueError) as exc:
        raise TransformError(f"Interest column {column!r} is not numeric.") from exc
    if math.isnan(value):
        raise TransformError(f"Interest column {column!r} contains no data.")
    if value < 0:
        raise TransformError(f"Interest for {keyword!r} must be non-negative, got {value}.")
    return value


def _column_for(frame: Any, keyword: str) -> Any:
    columns = getattr(frame, "columns", None)
    if columns is None:
        raise TransformError(f"Interest data has no columns; got {type(frame).__name__}.")
    for column in columns:
        if str(column).strip().casefold() == keyword.strip().casefold():
            return column
    raise TransformError(f"No interest column for keyword {keyword!r}.")


def _make_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
