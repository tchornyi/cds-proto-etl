-- Append-only snapshots of approximate absolute daily search volumes for the
-- terms configured in SEARCH_TERMS. Volumes are calibrated off a reference
-- term (REFERENCE_TERM / REFERENCE_TERM_DAILY_VOLUME), never exact counts.
CREATE TABLE search_volumes (
    snapshot_id UUID NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    term TEXT NOT NULL,
    search_volume BIGINT NOT NULL CHECK (search_volume >= 0),
    -- Mean 0-100 relative interest over the sampled window, kept for
    -- recalibration if the reference volume assumption changes.
    interest_avg REAL NOT NULL CHECK (interest_avg >= 0),
    reference_term TEXT NOT NULL,
    reference_volume BIGINT NOT NULL CHECK (reference_volume > 0),
    PRIMARY KEY (snapshot_id, term)
);

CREATE INDEX search_volumes_term_idx
    ON search_volumes (term, snapshot_at DESC);
