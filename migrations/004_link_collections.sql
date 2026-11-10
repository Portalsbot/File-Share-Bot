CREATE TABLE IF NOT EXISTS file_link_collections (
    id BIGSERIAL PRIMARY KEY,
    clone_id TEXT NOT NULL,
    collection_key TEXT NOT NULL,
    title TEXT NOT NULL,
    link_ids BIGINT[] NOT NULL DEFAULT '{}',
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(clone_id, collection_key)
);
CREATE INDEX IF NOT EXISTS file_link_collections_clone_idx
    ON file_link_collections(clone_id, id DESC);
