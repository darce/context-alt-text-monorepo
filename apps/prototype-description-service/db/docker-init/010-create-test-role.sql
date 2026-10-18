-- Create a privileged test role for local debugging/integration tests.
-- This role has elevated permissions (CREATEDB, CREATEROLE) but is NOT a SUPERUSER
-- so that RLS policies remain enforced during testing.
--
-- This script is idempotent and can be re-run safely.

DO
$$
BEGIN
    -- Create or update the test user
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'recognition_test_user') THEN
        CREATE ROLE recognition_test_user WITH
            LOGIN
            PASSWORD 'recognition_test_password'
            CREATEDB
            CREATEROLE;
        RAISE NOTICE 'Created test user: recognition_test_user';
    ELSE
        -- Ensure existing user has correct attributes (remove SUPERUSER if present)
        ALTER ROLE recognition_test_user WITH
            LOGIN
            PASSWORD 'recognition_test_password'
            NOSUPERUSER
            CREATEDB
            CREATEROLE;
        RAISE NOTICE 'Updated test user: recognition_test_user';
    END IF;
END
$$;

-- Grant privileges on the database
GRANT ALL PRIVILEGES ON DATABASE alt_context_service TO recognition_test_user;

-- Grant schema privileges
GRANT ALL PRIVILEGES ON SCHEMA public TO recognition_test_user;

-- Grant privileges on existing tables and sequences
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO recognition_test_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO recognition_test_user;

-- Grant privileges on future tables and sequences (if created by context_user)
ALTER DEFAULT PRIVILEGES FOR ROLE context_user IN SCHEMA public 
    GRANT ALL ON TABLES TO recognition_test_user;
ALTER DEFAULT PRIVILEGES FOR ROLE context_user IN SCHEMA public 
    GRANT ALL ON SEQUENCES TO recognition_test_user;

-- Allow modifying session configuration parameters needed for debugging
ALTER ROLE recognition_test_user SET log_min_duration_statement = 0;

