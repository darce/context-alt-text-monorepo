-- Enable required PostgreSQL extensions for recognition service
-- This script runs automatically on first container startup

-- UUID generation functions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Case-insensitive text type (useful for email/slug columns)
CREATE EXTENSION IF NOT EXISTS "citext";

-- Cryptographic functions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- pgvector for native vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify extensions installed
SELECT extname, extversion 
FROM pg_extension 
WHERE extname IN ('uuid-ossp', 'citext', 'pgcrypto', 'vector')
ORDER BY extname;
