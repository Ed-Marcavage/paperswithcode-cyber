-- Each observed quota exhaustion is an immutable event and durable cooldown.
CREATE TABLE IF NOT EXISTS assistant_provider_limits (
    id VARCHAR(36) PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    off_until TIMESTAMPTZ NOT NULL,
    provider_message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_assistant_provider_limits_off_until ON assistant_provider_limits(off_until);
