-- Creates (or re-passwords) the per-service login roles and gives each service its
-- own schema (ADR 0009 rules 1 and 10, decision A). Run as a superuser, in one
-- transaction. Idempotent: running it again rotates both passwords.
--
-- Passwords are never written into this file or onto a command line. The caller
-- sets them as session settings first:
--   greenloop.orchestrator_password, greenloop.broker_password
-- scripts/db-bootstrap.ps1 does that with psql's :'variable' quoting; the Postgres
-- tests do it with bound parameters.

-- Keep the dynamic CREATE/ALTER ROLE text (which holds the password) out of the
-- server log, including the error CONTEXT line if a statement fails.
SET log_statement = 'none';
SET log_min_duration_statement = -1;
SET log_min_error_statement = 'panic';
SET log_min_messages = 'panic';
SET password_encryption = 'scram-sha-256';

DO $bootstrap$
DECLARE
    role_names constant text[] := ARRAY['greenloop_orchestrator', 'greenloop_broker'];
    setting_names constant text[] := ARRAY['greenloop.orchestrator_password', 'greenloop.broker_password'];
    role_name text;
    role_password text;
    verb text;
BEGIN
    FOR i IN 1 .. array_length(role_names, 1) LOOP
        role_name := role_names[i];
        role_password := current_setting(setting_names[i], true);
        IF role_password IS NULL OR length(role_password) < 16 THEN
            RAISE EXCEPTION 'The password for % must be at least 16 characters.', role_name;
        END IF;
        verb := CASE WHEN EXISTS (SELECT FROM pg_roles WHERE rolname = role_name) THEN 'ALTER' ELSE 'CREATE' END;
        EXECUTE format(
            '%s ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
            verb, role_name, role_password
        );
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), role_name);
        PERFORM set_config(setting_names[i], '', false);
    END LOOP;
END
$bootstrap$;

-- The orchestrator owns public and runs its own migrations there.
ALTER SCHEMA public OWNER TO greenloop_orchestrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- The broker owns broker and runs its own migrations there.
CREATE SCHEMA IF NOT EXISTS broker AUTHORIZATION greenloop_broker;
ALTER SCHEMA broker OWNER TO greenloop_broker;
REVOKE ALL ON SCHEMA broker FROM PUBLIC;

ALTER ROLE greenloop_orchestrator SET search_path = public;
ALTER ROLE greenloop_broker SET search_path = broker;

RESET log_min_messages;
RESET log_min_error_statement;
RESET log_min_duration_statement;
RESET log_statement;
