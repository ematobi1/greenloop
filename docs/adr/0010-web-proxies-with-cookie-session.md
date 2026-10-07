# ADR 0010: The web app proxies the orchestrator and holds the token in a cookie

- Status: Accepted; implemented on feature/web-chat (Phase 2 web chat UI). Decision 1 (token paste) is superseded by [ADR 0012](0012-web-sign-in.md): the cookie now holds a server-side session token.
- Date: 2026-10-04

## Context

Phase 2 needs a browser chat UI over the orchestrator's conversation API, including streamed replies (`POST /v1/conversations/{id}/messages` with SSE events `message`, `delta`, `done`, `error`). The orchestrator authenticates with a bearer API token. Users don't have a login yet: the only credential is the token issued by the CLI. Memory and model output are untrusted and reach the browser in replies.

## Decision

1. **Token-paste sign-in is temporary.** The user pastes their API token once. Real user login (passwords or an identity provider, per-session credentials, revocation from the UI) is a later Phase 2 item and replaces this flow.
2. **The token lives only in an httpOnly cookie.** `POST /api/session` validates the token against the orchestrator (`GET /v1/conversations?limit=1`) and only then sets `__Host-greenloop_session`: `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=43200`. An explicit 12-hour Max-Age, because browsers restore session cookies with the session. The token never appears in a response body, a URL, `localStorage`/`sessionStorage`, or the server log (the end-to-end test greps the Next server's output for the token, `Authorization` and cookies).
3. **Every API call goes through the Next.js server.** Route handlers under `apps/web/src/app/api/` call the orchestrator over the compose network with `Authorization: Bearer`. The browser never learns the orchestrator URL (`ORCHESTRATOR_URL` is server-only, never `NEXT_PUBLIC_`). There is no catch-all proxy: only list/create conversations, list messages and send a message are exposed, and conversation ids must match `conv-<32 hex>` before they are forwarded. Pages request the orchestrator's maximum of 100 rows: the sidebar shows the 100 most recent conversations, and a longer conversation opens on its latest 100 messages with a note counting the earlier ones. The `provider` override is not forwarded.
4. **Cross-site writes are refused twice.** SameSite=Strict, plus every state-changing request must carry `Origin` equal to the configured `WEB_ORIGIN` (never derived from the incoming `Host` header) and, when it has a body, `Content-Type: application/json`.
5. **Upstream errors are relayed narrowly.** Only `error.code`, `error.message` and string `error.fields` pass through. A 401 from the orchestrator also clears the cookie. Outbound calls time out after 10 s waiting for headers, refuse redirects, and are aborted when the browser disconnects, so the orchestrator's turn cleanup runs.
6. **Untrusted text is rendered as text.** Messages and titles are React text children (escaped), with `white-space: pre-wrap`. No `dangerouslySetInnerHTML` or `innerHTML` anywhere in `apps/web/src`; a unit test enforces it. Sanitized markdown is a later step and needs a reviewed sanitizer dependency.
7. **Baseline security headers on every response:** `Content-Security-Policy: frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and no `X-Powered-By`.
8. **The orchestrator's CORS is closed.** Compose sets `CORS_ORIGINS='[]'`: no browser origin calls the orchestrator directly. `ALLOWED_HOSTS` keeps `orchestrator` for the compose network. The web container receives only `ORCHESTRATOR_URL` and `WEB_ORIGIN` (checked by `scripts/tests/check_compose_secrets.py`).

9. **Request bodies are capped** before parsing: 8 KB for sign-in and new conversations, 1 MB for a message (413 above). The web server's title and message length checks are loose outer bounds; the orchestrator enforces the real limits and its 422 is relayed.
10. **`src/server` stays on the server.** `src/server/deps.ts`, the module the route files import, starts with `import "server-only"`, so a client bundle that reaches it fails to build. A unit test also checks that no `"use client"` file imports server modules.
11. **The orchestrator owns the API shapes.** `apps/web/src/lib/api.ts` mirrors `ConversationOut`, `MessageOut` and the SSE events from `services/orchestrator/app/api/v1/chat.py` by hand; that file is the source of truth, and the mock orchestrator in `apps/web/e2e` copies its paging limit. Neither is contract-checked yet. Success bodies are passed through unchanged, so a field added to those responses reaches the browser.

## Consequences

- A stolen browser profile still yields a working API token for up to 12 hours, and the token is a long-lived API token, not a session credential. Real login (decision 1) fixes this with short-lived server-side sessions.
- `Secure` cookies work on `http://127.0.0.1` and `http://localhost` in Chromium and Firefox because they are secure contexts; Safari may refuse them over plain http. Anything beyond loopback must be served over HTTPS.
- Every chat byte passes through the web server. The SSE body is streamed through unchanged, and the end-to-end test checks that deltas reach the page before `done`, so nothing buffers it today.

## Later steps

- Strict Content Security Policy with per-request nonces (`script-src 'nonce-…' 'strict-dynamic'`), which needs Next's nonce support wired through the root layout.
- Sanitized markdown rendering.
- Real user login replacing token paste.
- Running the Playwright suite in CI (it needs a browser download).
- Generating the web types from the orchestrator's OpenAPI schema, and moving the SSE event payloads into `packages/contracts` before a second client (voice) needs them.
- An idle timeout on the relayed SSE stream; today it stays open until the orchestrator or the browser closes it.
- "Load earlier" paging for conversations and messages beyond 100.
