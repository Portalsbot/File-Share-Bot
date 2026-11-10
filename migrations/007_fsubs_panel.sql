CREATE TABLE IF NOT EXISTS file_fsub_channels (
    clone_id TEXT NOT NULL,
    channel_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    join_url TEXT NOT NULL,
    added_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (clone_id, channel_id)
);
