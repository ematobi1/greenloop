# ADR 0014: The HUD command center, its theme and the globe

- Status: Accepted
- Date: 2026-10-08

## Context

The web app was a set of plain pages. The owner wants one HUD-style command center (dark navy, cyan glow, glass panels) with real data, a holographic globe, the chat, and the Memory and Plans pages in the same theme, without weakening any security property from ADRs 0010 and 0012.

## Decision

1. **One theme, from tokens.** `apps/web/src/styles/tokens.css` defines colour, glow, glass, spacing, type and motion; components never hard-code them. Translucent variants use channel tokens (`rgb(var(--hud-accent-rgb) / 0.3)`), and the globe's three.js colours are named tokens in `lib/globe.ts` (`THEME_COLOURS`); `tests/tokens.test.mjs` fails on a raw colour in `globals.css` or the globe, or a globe colour that no longer matches its token. Every text colour reaches WCAG AA (4.5:1) on the page and panel backgrounds, computed from the file by `tests/tokens.test.mjs`. Motion tokens drop to 0 under `prefers-reduced-motion`.
2. **Type.** Orbitron (SIL OFL, bundled as two woff2 files with `OFL.txt` beside them, loaded through `next/font/local`) for headings, numbers and labels; system fonts for body and chat text. No remote fonts.
3. **Shell and routing.** Signed-in pages live in the `(hud)` route group: top bar (GreenLoop mark, tabs, status pill, clock, user menu with the real username from `GET /api/session` → `/v1/sessions/current`) and a left icon rail. `/` goes to `/chat`, the HUD. `/sign-in` is its own page. The group's layout only checks that the session cookie exists; the API's 401 stays the real check. A 401 from the orchestrator clears the session cookie and sets `__Host-greenloop_session_ended` (no secret, two minutes), so the next page load says the session ended; a wrong password at sign-in sets neither, and a successful sign-in clears the marker. This amends ADR 0012.
4. **Real data only.** `GET /api/overview` counts conversations, memories, plan drafts (`/v1/plans?status=draft`), pending approvals and agents from the orchestrator's list endpoints; a failing source is `null` with a note, shown as "—", never a guess. `GET /api/health` returns the status of the orchestrator, broker and database (the orchestrator's `/v1/health` now probes the broker within 2 s), statuses only, no addresses. A service that isn't configured counts neither up nor down. Both need a session the orchestrator accepts (health checks `/v1/sessions/current` before probing, because the probe itself is unauthenticated), refresh every 30 s while the tab is visible, and show when they last updated. A partial outage reads "degraded" in amber with "2 of 3 services up".
5. **The globe.** three.js 0.180.0 (MIT, pinned, bundled), loaded with a dynamic import only by `HudGlobe`. Six nodes orbit a wireframe globe on a ring platform; each node's colour is the health of the service it actually measures, and Agents, Tools and Approvals say "registry reachable" or "broker reachable". The core pulses while a reply is pending, flares with each streamed delta, and turns amber on error (`lib/globe.ts`, unit-tested without three.js). Reduced motion, screens under 768 px and the globe's own Pause motion button draw one still frame; nodes hold still while pointed at or focused (WCAG 2.2.2); a hidden tab draws nothing; frames are capped at 30 per second; without WebGL a CSS globe stands in. Node labels are DOM buttons over the canvas, keyboard reachable, with their status as text.
6. **The chat is the HUD.** The assistant panel and the bottom "Ask GreenLoop…" bar are the existing chat: plain-text rendering, Remember, Draft a plan, suggested prompts; sending without an open conversation starts one. Live activity merges recent conversations, memories and plans; the audit feed joins in Phase 3.
7. **Security unchanged.** Every call still goes through `/api` on the server with the cookie session; text renders as React text (no `dangerouslySetInnerHTML`); security headers stay. Nothing needs `eval`, inline scripts or remote assets, so a strict nonce-based CSP can still be added later.

## Consequences

- three.js is a separate chunk, loaded only on the HUD by the dynamic import: 696,018 bytes raw, 174,510 bytes gzipped (level 9), measured from `next build` on 2026-10-08. The globe's own chunk adds 20,275 bytes raw, 7,260 gzipped.
- Machines without GPU acceleration render WebGL in software; the Playwright suite runs with reduced motion by default for that reason, and the globe's own tests opt back in.
- Polling is per browser tab, on one 30-second timer: each refresh makes 7 calls to the orchestrator (overview's 5 counts, the session check and health probe) plus 2 for live activity, which reloads after it. Many open tabs multiply that.
