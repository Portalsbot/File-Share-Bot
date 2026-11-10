ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS max_files_per_request INTEGER;
