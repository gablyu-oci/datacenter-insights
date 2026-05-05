-- Provision a least-privilege Postgres role for the AI Insights agent.
-- Idempotent: safe to re-run.
--
-- Usage (psql):
--     psql "$SUPERUSER_DSN" \
--          -v pw="'$AI_AGENT_DB_PASSWORD'" \
--          -v dbname="strategic_insights" \
--          -f provision_ai_agent_role.sql
--
-- The companion Python wrapper `provision_ai_agent_role.py` injects these
-- variables when invoked from the CLI.

-- 1) Create the role only if it doesn't already exist.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ai_agent') THEN
        EXECUTE format(
            'CREATE ROLE ai_agent NOSUPERUSER NOCREATEDB NOCREATEROLE LOGIN PASSWORD %L',
            :'pw'
        );
    ELSE
        EXECUTE format('ALTER ROLE ai_agent WITH LOGIN PASSWORD %L', :'pw');
    END IF;
END
$$;

-- 2) Tighten attributes & limits.
ALTER ROLE ai_agent NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE ai_agent SET statement_timeout = '5s';
ALTER ROLE ai_agent SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE ai_agent SET lock_timeout = '2s';
ALTER ROLE ai_agent CONNECTION LIMIT 4;

-- 3) Grant CONNECT on the target database.
GRANT CONNECT ON DATABASE :"dbname" TO ai_agent;

-- 4) Schema-level grants. Only `public` is exposed.
GRANT USAGE ON SCHEMA public TO ai_agent;

-- 5) Read-only on every existing table.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ai_agent;

-- 6) Future tables created by the application role automatically grant SELECT.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ai_agent;

-- 7) Sequences (for nextval reads if they appear in views) — read-only.
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO ai_agent;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO ai_agent;

-- 8) Explicitly REVOKE write/DDL bits to be safe (no-op if not granted).
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA public FROM ai_agent;
REVOKE CREATE ON SCHEMA public FROM ai_agent;
REVOKE CREATE ON DATABASE :"dbname" FROM ai_agent;
