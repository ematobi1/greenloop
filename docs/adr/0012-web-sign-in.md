# ADR 0012: Web sign-in with username, password and server-side sessions

- Status: Accepted; implemented on feature/phase2-rest. Replaces ADR 0010 decision 1 (token paste).
- Date: 2026-10-05

## Context

ADR 0010 let the browser sign in by pasting a long-lived API token, as a stopgap. That token never expires on its own, can't be revoked per browser, and gives the web app the same credential the CLI uses. Phase 2 needs real sign-in.

## Decision

1. **Username and password, hashed with argon2id.** `user_credentials` holds one username (3 to 64 of `a-z0-9._-`, case-insensitive) and an argon2id hash (argon2-cffi defaults, the RFC 9106 low-memory profile) per principal. Passwords are 12 to 256 characters. Hashes are upgraded on sign-in when the parameters change. Users are created with `python -m app.cli create-user <principal> <username>`; the password comes from a hidden prompt asked twice, or `GREENLOOP_NEW_PASSWORD` for scripts, never from a command-line argument.
2. **Server-side sessions.** `POST /v1/sessions` returns a `gls_` token (256 random bits) once; only its SHA256 is stored in `user_sessions` with a 12-hour expiry. The bearer check accepts session tokens alongside API tokens (`glt_`), and a disabled principal's sessions stop working at once. The web server keeps the session token in the `__Host-` cookie from ADR 0010, with `Max-Age` capped at the session's remaining lifetime.
3. **Failures reveal nothing.** A wrong password and an unknown username get the same 401 `INVALID_CREDENTIALS`; an unknown username still runs a full argon2 verification against a dummy hash.
4. **Lockout and rate limit.** Five failures in a row lock that username for 15 minutes (429 `SIGN_IN_THROTTLED` with `Retry-After`), counted in `login_throttle` for known and unknown usernames alike, so a lockout doesn't reveal that an account exists. The row is locked `FOR UPDATE`, so parallel attempts are all counted. A success resets the count. Each orchestrator process also allows at most 30 sign-in attempts a minute in total, to slow password spraying across usernames.
5. **Sign-out.** `DELETE /v1/sessions/current` revokes the session the request used; `DELETE /v1/sessions` revokes every session of the principal ("sign out everywhere"). Both refuse API tokens (409), which are revoked with the CLI. Changing a password (`set-password`) revokes every session. The web server clears the cookie even when the orchestrator can't be reached, and tells the user when "everywhere" failed.
6. **Audit and logs.** Successful and failed sign-ins of known users, sign-outs and password changes are audited. `glt_` and `gls_` token shapes are added to the redactor. Tests check that passwords and tokens never reach logs.
7. **API tokens stay for the CLI and services.** The web UI no longer offers token paste.

## Consequences

- An attacker who can reach the orchestrator directly can still guess passwords at the global rate; the port is bound to 127.0.0.1 in compose. Per-client rate limits need a trusted client address and come with deployment.
- Lockout lets someone deny a user sign-in for 15 minutes by failing on purpose. Accepted for a single-user system; an unlock command (`set-password` or a future `unlock-user`) is the recovery.
- There is no password reset by email; the CLI resets passwords.
- The dev database needs `alembic upgrade head` and a `create-user` before the web app can be used.
