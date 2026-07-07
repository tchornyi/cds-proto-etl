# AGENTS.md

Guidance for Agents (and humans) working in this repository.

## What this is

A small, self-contained **ETL** that takes a point-in-time **snapshot** of the
top 25 trending Google searches and stores them in PostgreSQL. Each run upserts
up to 25 rows (rank 1–25), all sharing a single `snapshot_id` / `snapshot_at`,
into the table **`current_trends`**. The table keeps one row per term per
local calendar day (`trend_date`, bucketed by `TRENDS_TIMEZONE`, default
system timezone): a rerun on the same day refreshes that day's row, a new day
inserts a fresh one — per-day trend history.

- **Extract** — `extract.py`: fetches the "Trending Now" feed via
  [trendspy](https://pypi.org/project/trendspy/) (Google Trends has no official
  API; this wraps the same endpoints the trends.google.com UI uses — no API key).
  One request returns the full trending list for the configured geo.
- **Transform** — `transform.py`: normalises raw trend entries into flat, frozen
  `TrendRecord` dataclasses: rank (1–25), search term, **approximate search
  volume**, volume growth %, related queries (JSONB), trend start time. Truncates
  the feed to the top 25 by rank. All timestamps made timezone-aware before insert.
- **Load** — `load.py`: one bulk `executemany` upsert (`ON CONFLICT
  (term, trend_date)`) inside a single transaction.
- **Migrate** — `migrate.py`: forward-only SQL migration runner; tracks applied
  files in `schema_migrations`. `current_trends` is created here, never by hand.

## Layout

```
migrations/                       # NNN_*.sql, applied in filename order
  001_create_current_trends.sql
src/google_trends_etl/
  config.py      # DB creds + TRENDS_GEO from env (DATABASE_URL or PG* vars); loads .env
  db.py          # psycopg connection helper
  migrate.py     # migration runner (entry point: google-trends-migrate)
  extract.py     # trendspy client (Trending Now feed)
  transform.py   # raw trend entry -> TrendRecord
  load.py        # bulk insert
  main.py        # orchestrates E->T->L (entry point: google-trends-etl)
```

One module per pipeline stage. A future second pipeline in this repo gets its
own `extract_x.py` / `transform_x.py` / `load_x.py` / `x_main.py` set plus a new
entry point — stages are never shared across pipelines except `db.py`,
`config.py`, and `migrate.py`.

## Running (uv)

Project runs under [uv](https://docs.astral.sh/uv/); dependencies resolve from
`pyproject.toml` (hatchling build, `[project.scripts]` entry points).

```bash
cp .env.example .env         # then edit values

# Full ETL cycle: applies pending migrations, then extract -> transform -> load.
uv run google-trends-etl

# Optional
uv run google-trends-migrate                          # migrations only
uv run google-trends-etl --skip-migrations --log-level DEBUG
uv run google-trends-etl --geo GB                     # override TRENDS_GEO for one run
```

## Configuration

Database credentials come **only** from the environment (`config.py`):

- `DATABASE_URL` — full libpq connection string; takes precedence, **or**
- `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`.

Pipeline settings:

- `TRENDS_GEO` — two-letter geo code for the trending feed (default: `US`).
- `TRENDS_TOP_N` — how many top trends to keep (default: `25`).
- `TRENDS_TIMEZONE` — IANA timezone for `trend_date` day bucketing
  (e.g. `Europe/Kyiv`; default: system local timezone).

A local `.env` is auto-loaded; real environment variables always override it.
Fail fast with a clear message when required variables are missing.
`os.environ` values are always strings — parse (`int(...)`) defensively.

## Schema (`current_trends`)

- `snapshot_id UUID`, `snapshot_at TIMESTAMPTZ` — last run that touched the row.
- `trend_date DATE` — local day the term trended (`TRENDS_TIMEZONE`); PK is
  `(term, trend_date)`.
- `rank SMALLINT` — 1–25 position in the trending list at last refresh.
- `term TEXT` — the trending search query.
- `search_volume INTEGER` — approximate search volume as reported by Google
  (e.g. the "500K+" figures, normalised to an integer lower bound).
- `volume_growth_pct INTEGER NULL` — reported growth, when present.
- `trend_started_at TIMESTAMPTZ NULL` — when Google says the trend began.
- `related_queries JSONB NULL` — raw related-query list, stored as-is.

## Conventions

- **Schema changes go through migrations.** Add the next `NNN_*.sql`; never edit
  an applied migration or alter tables by hand. The runner applies files with
  the session `TimeZone` set from `TRENDS_TIMEZONE` (falling back to the
  host's UTC offset), so `timestamptz::date` casts in migrations bucket to
  local days.
- One row per `(term, trend_date)` — a same-day rerun updates that day's row
  (volume, timestamps, rank, growth, related queries); a new local day inserts
  a new row. Rows are never deleted; history is queried by `trend_date`.
- Timestamps stored as `TIMESTAMPTZ`; make them timezone-aware in transform.
- A single trend entry failing to transform is logged and skipped, not fatal;
  a failing extract or load is fatal. Fewer than 25 rows in a snapshot is
  acceptable (feed may be short or entries skipped) — log the count.
- **Unofficial API caveat:** trendspy scrapes undocumented endpoints; breakage
  shows up as extract-stage schema/HTTP errors, not transform bugs. Pin its
  version in `pyproject.toml` and treat upgrades as deliberate changes.
- Volume figures are Google's coarse approximations ("100K+", "1M+") — store
  the normalised lower bound, never present them as exact counts.
- **Absolute imports only** (`from google_trends_etl.x import y`, never
  `from .x`). The deployment Dockerfile is auto-generated and runs
  `uv run python src/google_trends_etl/main.py` — file-path execution breaks
  relative imports.
- Entry-point functions: `main()` parses args and configures logging; `run()`
  holds the pipeline logic and returns rows inserted (testable without CLI).
- Deployed via auto-generated Docker image, scheduled by Airflow
  (DockerSwarmOperator); the container is a batch job that exits when done.
```