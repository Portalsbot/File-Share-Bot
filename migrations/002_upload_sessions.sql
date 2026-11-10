CREATE TABLE IF NOT EXISTS file_upload_sessions (
    clone_id TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    source_chat_id BIGINT NOT NULL,
    message_ids BIGINT[] NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (clone_id, user_id)
);
CREATE INDEX IF NOT EXISTS file_upload_sessions_active_idx
    ON file_upload_sessions(clone_id, active);
