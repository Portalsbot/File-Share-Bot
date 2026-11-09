CREATE TABLE IF NOT EXISTS bot_message_templates (
    clone_id TEXT NOT NULL,
    template_key TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (clone_id, template_key)
);
CREATE TABLE IF NOT EXISTS bot_message_buttons (
    clone_id TEXT NOT NULL,
    template_key TEXT NOT NULL,
    buttons JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (clone_id, template_key)
);
CREATE TABLE IF NOT EXISTS bot_users (
    clone_id TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_banned BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (clone_id, user_id)
);

CREATE TABLE IF NOT EXISTS file_share_links (
    id BIGSERIAL PRIMARY KEY,
    clone_id TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    source_chat_id BIGINT NOT NULL,
    message_ids BIGINT[] NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    access_count BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_file_share_links_clone ON file_share_links(clone_id);
CREATE TABLE IF NOT EXISTS file_delivery_events (
    id BIGSERIAL PRIMARY KEY,
    clone_id TEXT NOT NULL,
    token TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS file_collections (
    id BIGSERIAL PRIMARY KEY,
    clone_id TEXT NOT NULL,
    collection_key TEXT NOT NULL,
    title TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(clone_id, collection_key)
);
CREATE TABLE IF NOT EXISTS file_settings (
    clone_id TEXT NOT NULL,
    setting_key TEXT NOT NULL,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(clone_id, setting_key)
);
