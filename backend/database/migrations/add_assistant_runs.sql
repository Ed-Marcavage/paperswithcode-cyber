-- Cyber catalog only; apply after add_assistant_history.sql.
CREATE TABLE IF NOT EXISTS assistant_runs (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
    message_id VARCHAR(36) NOT NULL UNIQUE REFERENCES assistant_messages(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status VARCHAR(24) NOT NULL,
    error TEXT,
    model VARCHAR(200) NOT NULL,
    prompt_hash VARCHAR(64) NOT NULL,
    prompt_version VARCHAR(80) NOT NULL,
    surface VARCHAR(20) NOT NULL,
    site_path VARCHAR(500) NOT NULL,
    analytics_session_id VARCHAR(36),
    feedback_rating VARCHAR(8),
    feedback_note VARCHAR(500)
);
CREATE INDEX IF NOT EXISTS ix_assistant_runs_conversation_id ON assistant_runs(conversation_id);
CREATE INDEX IF NOT EXISTS ix_assistant_runs_started_at ON assistant_runs(started_at);
CREATE TABLE IF NOT EXISTS assistant_run_steps (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES assistant_runs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind VARCHAR(16) NOT NULL,
    detail JSON NOT NULL,
    UNIQUE (run_id, position)
);
CREATE INDEX IF NOT EXISTS ix_assistant_run_steps_run_id ON assistant_run_steps(run_id);
