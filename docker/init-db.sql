-- Auto-executed by PostgreSQL on first container start
-- Creates required extensions for e-learning-backend

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Verify extensions
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('vector', 'uuid-ossp');

-- Output confirmation
DO $$
BEGIN
    RAISE NOTICE '✅ pgvector extension installed successfully (version: %)',
        (SELECT extversion FROM pg_extension WHERE extname='vector');
END $$;
