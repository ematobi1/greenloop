-- One-time change for an existing database (ADR 0009 decision B): every object in
-- public moves to greenloop_orchestrator, so the orchestrator role can run its own
-- migrations and the bootstrap superuser is no longer needed at runtime.
-- Run as a superuser after bootstrap-roles.sql, in one transaction. Idempotent.
--
-- Extension members are left alone. Sequences and indexes owned by a table move
-- with the table. A multirange does not follow its range type, so both move.
-- The last block refuses to commit if anything is left behind.

DO $transfer$
DECLARE
    orchestrator constant regrole := 'greenloop_orchestrator'::regrole;
    item record;
BEGIN
    FOR item IN
        SELECT c.oid::regclass AS name,
               CASE c.relkind
                   WHEN 'S' THEN 'SEQUENCE'
                   WHEN 'v' THEN 'VIEW'
                   WHEN 'm' THEN 'MATERIALIZED VIEW'
                   WHEN 'f' THEN 'FOREIGN TABLE'
                   ELSE 'TABLE'
               END AS kind
        FROM pg_class c
        WHERE c.relnamespace = 'public'::regnamespace
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND c.relowner <> orchestrator
          AND NOT EXISTS (
              SELECT FROM pg_depend d
              WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('a', 'i', 'e')
          )
    LOOP
        EXECUTE format('ALTER %s %s OWNER TO greenloop_orchestrator', item.kind, item.name);
    END LOOP;

    FOR item IN
        SELECT p.oid::regprocedure AS name,
               CASE p.prokind WHEN 'p' THEN 'PROCEDURE' WHEN 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END AS kind
        FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace
          AND p.proowner <> orchestrator
          AND NOT EXISTS (
              SELECT FROM pg_depend d
              WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
          )
    LOOP
        EXECUTE format('ALTER %s %s OWNER TO greenloop_orchestrator', item.kind, item.name);
    END LOOP;

    FOR item IN
        SELECT t.oid::regtype AS name,
               CASE t.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END AS kind
        FROM pg_type t
        LEFT JOIN pg_class c ON c.oid = t.typrelid
        WHERE t.typnamespace = 'public'::regnamespace
          AND t.typowner <> orchestrator
          AND (t.typtype IN ('e', 'd', 'r', 'm') OR (t.typtype = 'c' AND c.relkind = 'c'))
          AND NOT EXISTS (
              SELECT FROM pg_depend d
              WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e'
          )
    LOOP
        EXECUTE format('ALTER %s %s OWNER TO greenloop_orchestrator', item.kind, item.name);
    END LOOP;
END
$transfer$;

DO $verify$
DECLARE
    orchestrator constant regrole := 'greenloop_orchestrator'::regrole;
    leftovers text;
BEGIN
    SELECT string_agg(name, ', ' ORDER BY name) INTO leftovers
    FROM (
        SELECT c.oid::regclass::text AS name
        FROM pg_class c
        WHERE c.relnamespace = 'public'::regnamespace AND c.relowner <> orchestrator
          AND NOT EXISTS (
              SELECT FROM pg_depend d
              WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'
          )
        UNION ALL
        SELECT p.oid::regprocedure::text
        FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace AND p.proowner <> orchestrator
          AND NOT EXISTS (
              SELECT FROM pg_depend d
              WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
          )
        UNION ALL
        SELECT t.oid::regtype::text
        FROM pg_type t
        WHERE t.typnamespace = 'public'::regnamespace AND t.typowner <> orchestrator
          AND NOT EXISTS (
              SELECT FROM pg_depend d
              WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e'
          )
    ) AS remaining;
    IF leftovers IS NOT NULL THEN
        RAISE EXCEPTION 'Objects in public still not owned by greenloop_orchestrator: %', leftovers;
    END IF;
    IF (SELECT nspowner FROM pg_namespace WHERE nspname = 'public') <> orchestrator THEN
        RAISE EXCEPTION 'Schema public is not owned by greenloop_orchestrator; run bootstrap-roles.sql first.';
    END IF;
END
$verify$;
