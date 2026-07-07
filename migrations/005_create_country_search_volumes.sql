-- One row per (term, country, local day) of approximate search volume:
-- a rerun on the same day updates that day's row, a new day inserts a fresh
-- one. Volumes distribute the term's calibrated global volume by each
-- country's share of Google's regional interest — approximations, not counts.
CREATE TABLE country_search_volumes (
    term TEXT NOT NULL,
    country_code TEXT NOT NULL,
    country_name TEXT NULL,
    volume_date DATE NOT NULL,
    search_volume BIGINT NOT NULL CHECK (search_volume >= 0),
    -- Google's 0-100 relative interest for the country.
    interest SMALLINT NOT NULL CHECK (interest BETWEEN 0 AND 100),
    snapshot_id UUID NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (term, country_code, volume_date)
);

CREATE INDEX country_search_volumes_date_idx
    ON country_search_volumes (volume_date DESC);
