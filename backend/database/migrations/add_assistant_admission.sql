-- Cyber catalog only. Apply before enabling assistant writes.
-- No IP addresses; rolling timestamps survive conversation deletion.
CREATE TABLE IF NOT EXISTS assistant_admission (
    visitor_hash VARCHAR(64) PRIMARY KEY,
    turns JSON NOT NULL,
    conversations JSON NOT NULL,
    active_run_id VARCHAR(36),
    active_until TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_assistant_admission_active_run_id ON assistant_admission(active_run_id);
CREATE INDEX IF NOT EXISTS ix_assistant_admission_updated_at ON assistant_admission(updated_at);
