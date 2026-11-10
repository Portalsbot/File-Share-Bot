ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS max_files_per_request INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'bot_users_max_files_per_request_positive'
    ) THEN
        ALTER TABLE bot_users
            ADD CONSTRAINT bot_users_max_files_per_request_positive
            CHECK (max_files_per_request IS NULL OR max_files_per_request > 0);
    END IF;
END $$;
