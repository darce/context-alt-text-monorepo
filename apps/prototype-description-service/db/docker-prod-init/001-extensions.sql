-- Production-safe extension bootstrap (no test roles or dev fixtures).
-- Mounted into postgres via docker-compose.prod.yml.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;

-- Verification
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('uuid-ossp', 'citext', 'pgcrypto', 'vector')
ORDER BY extname;
