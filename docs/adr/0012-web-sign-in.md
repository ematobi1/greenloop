# ADR 0012: Web sign-in with username, password and server-side sessions

- Status: Accepted; implemented on feature/phase2-rest. Replaces ADR 0010 decision 1 (token paste).
- Date: 2026-10-05

## Context

ADR 0010 let the browser sign in by pasting a long-lived API token, as a stopgap. That token never expires on its own, can't be revoked per browser, and gives the web app the same credential the CLI uses. Phase 2 needs real sign-in.

## Decision

1. **Username and password, hashed with argon2id.** `user_credentials` holds one username (3 to 64 of `a-z0-9._-`, case-insensitive) and an argon2id hash (argon2-cffi defaults, the RFC 9106 low-memory profile) per principal. Passwords are 12 to 256 characters. Hashes are upgraded on sign-in when the parameters change. Users are created with `python -m app.cli create-user <principal> <username>`; the password comes from a hidden prompt asked twice, or `GREENLOOP_NEW_PASSWORD` for scripts, never from a command-line argument.
2. **Server-side sessions.** `POST /v1/sessions` returns a `gls_` token (256 random bits) once; only its SHA256 is stored in `user_sessions` with a 12-hour expiry. The bearer check accepts session tokens alongside API tokens (`glt_`), and a disabled principal's sessions stop working at once. The web server keeps the session token in the `__Host-` cookie from ADR 0010, with `Max-Age` capped at the session's remaining lifetime.
3. **Failures reveal nothing.** A wrong password and an unknown username get the same 401 `INVALID_CREDENTIALS`; an unknown username still runs a full argon2 verification against a dummy hash.
4. **Lockout and rate limit.** Five failures in a row lock that username for 15 minutes (429 `SIGN_IN_THROTTLED` with `Retry-After`), counted in `login_throttle` for known and unknown usernames alike, so a lockout doesn't reveal that an account exists. Failures are added atomically, so parallel attempts are all counted. A success resets the count. `python -m app.cli unlock-user <username>` lifts a lockout. Each orchestrator process runs at most 4 argon2 verifications at once; an attempt that finds them all busy gets 429 at once rather than waiting, so a flood never parks server threads. Past 30 failures a minute, further failures get 429 instead of 401; successes are never counted or refused. No row lock is held while a password is checked: the lockout is read before verification and failures are added with one atomic UPDATE after it, so a few attempts already in flight when a username locks still get answers (bounded by the 4 slots). Stale throttle rows (idle an hour, unlocked) and sessions expired or revoked over a day ago are pruned in small batches on every attempt.
5. **Sign-out.** `DELETE /v1/sessions/current` revokes the session the request used; `DELETE /v1/sessions` revokes every session of the principal ("sign out everywhere"). Both refuse API tokens (409), which are revoked with the CLI. Changing a password (`set-password`) revokes every session. The web server clears the cookie even when the orchestrator can't be reached, and tells the user when "everywhere" failed.
6. **Audit and logs.** Successful and failed sign-ins of known users, sign-outs and password changes are audited. `glt_` and `gls_` token shapes are added to the redactor. Tests check that passwords and tokens never reach logs.
7. **API tokens stay for the CLI and services.** The web UI no longer offers token paste.

## Consequences

- An attacker who can reach the orchestrator gets at most 5 guesses per username every 15 minutes; spraying many usernames is bounded only by the verification cap. The port is bound to 127.0.0.1 in compose. Per-client rate limits need a trusted client address and come with deployment.
- A flood that keeps all 4 verification slots busy delays every sign-in, the owner's included (429 until a slot frees); it can't lock anyone out for longer than the flood lasts.
- Lockout lets someone who knows a username deny that user sign-in by failing on purpose every 15 minutes. Accepted for a single-user system with the orchestrator bound to 127.0.0.1; `unlock-user` is the recovery. Per-source limits need a trusted client address (Next keeps a client-supplied `X-Forwarded-For`), which comes with deployment.
- There is no password reset by email; the CLI resets passwords.
- The dev database needs `alembic upgrade head` and a `create-user` before the web app can be used.
