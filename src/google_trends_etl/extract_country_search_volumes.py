"""Extract per-country relative interest for the configured search terms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence

from trendspy import Trends

TIMEFRAME = "now 1-d"
# Google Trends compares at most 5 keywords per request; one slot is reserved
# for the calibration reference term that rides along in every batch.
MAX_TERMS_PER_BATCH = 4


class CountryTrendsClient(Protocol):
    def interest_over_time(self, keywords: Sequence[str], *, timeframe: str) -> Any:
        ...

    def interest_by_region(
        self,
        keyword: str,
        *,
        timeframe: str,
        inc_low_vol: bool = False,
    ) -> Any:
        ...


@dataclass(frozen=True)
class InterestBatch:
    terms: tuple[str, ...]
    reference_term: str
    # pandas DataFrame: one 0-100 interest column per requested keyword.
    frame: Any


@dataclass(frozen=True)
class CountryInterest:
    term: str
    # pandas DataFrame: 0-100 relative interest per country.
    frame: Any


@dataclass(frozen=True)
class CountryExtract:
    interest_batches: tuple[InterestBatch, ...]
    country_interest: tuple[CountryInterest, ...]


def extract_country_interest(
    terms: Iterable[str],
    reference_term: str,
    *,
    timeframe: str = TIMEFRAME,
    include_low_volume_geos: bool = True,
    client: CountryTrendsClient | None = None,
) -> CountryExtract:
    trends_client = client or Trends()
    unique_terms = list(dict.fromkeys(terms))

    batches: list[InterestBatch] = []
    for start in range(0, len(unique_terms), MAX_TERMS_PER_BATCH):
        chunk = unique_terms[start : start + MAX_TERMS_PER_BATCH]
        keywords = list(dict.fromkeys([*chunk, reference_term]))
        frame = trends_client.interest_over_time(keywords, timeframe=timeframe)
        batches.append(
            InterestBatch(terms=tuple(chunk), reference_term=reference_term, frame=frame)
        )

    country_interest = tuple(
        CountryInterest(
            term=term,
            frame=trends_client.interest_by_region(
                term,
                timeframe=timeframe,
                inc_low_vol=include_low_volume_geos,
            ),
        )
        for term in unique_terms
    )

    return CountryExtract(
        interest_batches=tuple(batches),
        country_interest=country_interest,
    )
