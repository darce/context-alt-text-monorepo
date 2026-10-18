-- UUID helper functions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Case-insensitive text type for future slugs/emails
CREATE EXTENSION IF NOT EXISTS "citext";

-- Cryptographic helpers (for future token hashing)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- pgvector required for embedding storage/query
CREATE EXTENSION IF NOT EXISTS vector;

-- Verification (outputs when container starts)
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('uuid-ossp', 'citext', 'pgcrypto', 'vector')
ORDER BY extname;
