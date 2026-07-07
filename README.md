# cds-proto-etl

A small ETL that snapshots the top Google Trending Now searches into PostgreSQL.
Each successful run upserts up to 25 rows (rank 1–25) into `current_trends`,
all sharing a single `snapshot_id` / `snapshot_at`. The table keeps one row per
term per local calendar day (`TRENDS_TIMEZONE`, default system timezone): a
rerun on the same day refreshes that day's row, while the first appearance on
a new day inserts a fresh one — preserving per-day trend history.

Data comes from the Google Trends "Trending Now" feed via
[trendspy](https://pypi.org/project/trendspy/) — Google Trends has no official
API, so trendspy wraps the same endpoints the trends.google.com UI uses. No API
key required.

## Pipeline

| Stage     | Module         | What it does                                                                    |
| --------- | -------------- | ------------------------------------------------------------------------------- |
| Extract   | `extract.py`   | Fetches the Trending Now feed for the configured geo (one request).             |
| Transform | `transform.py` | Normalises raw entries into flat, frozen `TrendRecord` dataclasses.             |
| Load      | `load.py`      | One bulk `executemany` upsert inside a single transaction.                      |
| Migrate   | `migrate.py`   | Forward-only SQL migration runner; tracks applied files in `schema_migrations`. |

Rows conflict on `(term, trend_date)`: same term on the same local day updates
the existing row (search volume, timestamps, rank, growth, related queries);
a new day gets a new row. Daily trend history is queried by `trend_date`.

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and a reachable
PostgreSQL database.

```bash
cp .env.example .env
```

Then edit `.env` with either `DATABASE_URL` or all `PG*` settings.

| Variable                 | Purpose                                                        | Default |
| ------------------------ | -------------------------------------------------------------- | ------- |
| `DATABASE_URL`           | Full libpq connection string; takes precedence when set        | —       |
| `PGHOST` … `PGSSLMODE`   | Individual connection settings, used when `DATABASE_URL` empty | —       |
| `TRENDS_GEO`             | Two-letter geo code for the trending feed                      | `US`    |
| `TRENDS_TOP_N`           | How many top trends to keep (1–25)                             | `25`    |
| `TRENDS_TIMEZONE`        | IANA timezone for `trend_date` day bucketing (e.g. `Europe/Kyiv`) | system local |
| `PRE_LOAD_SLEEP_SECONDS` | Simulated delay before loading records into PostgreSQL         | `20`    |

A local `.env` is auto-loaded; real environment variables always override it.

## Run

```bash
uv run google-trends-etl
```

Optional commands:

```bash
uv run google-trends-migrate
uv run google-trends-etl --skip-migrations --log-level DEBUG
uv run google-trends-etl --geo GB
```

The main ETL command applies pending migrations before extracting and loading
data, so Docker entrypoints only need to run `uv run google-trends-etl`.

## Schema (`current_trends`)

| Column              | Type          | Notes                                                        |
| ------------------- | ------------- | ------------------------------------------------------------ |
| `snapshot_id`       | `UUID`        | Last run that touched the row                                |
| `snapshot_at`       | `TIMESTAMPTZ` | When the row was last refreshed                              |
| `trend_date`        | `DATE`        | Local day the term trended (`TRENDS_TIMEZONE`); one row per term per day |
| `rank`              | `SMALLINT`    | 1–25 position in the trending list at last refresh           |
| `term`              | `TEXT`        | The trending search query                                    |
| `search_volume`     | `INTEGER`     | Google's coarse figure ("500K+") normalised to a lower bound |
| `volume_growth_pct` | `INTEGER`     | Reported growth, when present                                |
| `trend_started_at`  | `TIMESTAMPTZ` | When Google says the trend began                             |
| `related_queries`   | `JSONB`       | Raw related-query list, stored as-is                         |

Primary key is `(term, trend_date)`. Schema changes go through migrations —
add the next `NNN_*.sql` in `migrations/`; never edit an applied migration.

## Caveats

- trendspy scrapes undocumented endpoints; breakage shows up as extract-stage
  schema/HTTP errors. Its version is pinned in `pyproject.toml` — treat
  upgrades as deliberate changes.
- Volume figures are Google's approximations, never exact counts.
- Fewer than 25 rows in a snapshot is acceptable (short feed or skipped
  entries) — the run logs the count.

## Deployment

Deployed via an auto-generated Docker image and scheduled by Airflow
(DockerSwarmOperator). The container is a batch job that runs one ETL cycle and
exits.

See [AGENTS.md](AGENTS.md) for contributor conventions.
