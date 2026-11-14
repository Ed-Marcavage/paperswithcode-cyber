-- Cyber catalog only. Apply to its local database before enabling the assistant.
CREATE TABLE IF NOT EXISTS assistant_conversations (
    id VARCHAR(36) PRIMARY KEY,
    visitor_hash VARCHAR(64) NOT NULL,
    title VARCHAR(60) NOT NULL,
    question_count INTEGER NOT NULL DEFAULT 0 CHECK (question_count BETWEEN 0 AND 10),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_assistant_conversations_visitor_hash ON assistant_conversations(visitor_hash);
CREATE INDEX IF NOT EXISTS ix_assistant_conversations_created_at ON assistant_conversations(created_at);
CREATE TABLE IF NOT EXISTS assistant_messages (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    role VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL DEFAULT '',
    status VARCHAR(24) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (conversation_id, position)
);
CREATE INDEX IF NOT EXISTS ix_assistant_messages_conversation_id ON assistant_messages(conversation_id);
CREATE TABLE IF NOT EXISTS assistant_tool_calls (
    id VARCHAR(36) PRIMARY KEY,
    message_id VARCHAR(36) NOT NULL REFERENCES assistant_messages(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    detail JSON NOT NULL,
    UNIQUE (message_id, position)
);
CREATE INDEX IF NOT EXISTS ix_assistant_tool_calls_message_id ON assistant_tool_calls(message_id);
