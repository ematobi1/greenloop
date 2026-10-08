// Request handlers behind the app/api route files, kept free of Next imports so the
// tests can call them with plain Request objects. Only these paths reach the
// orchestrator; there is no catch-all proxy.

import type { ServerConfig } from "./config.ts";
import { BODY_TOO_LARGE, readJsonBody, rejectCrossSite, rejectNonJson } from "./guard.ts";
import { emptyResponse, errorResponse, jsonResponse } from "./http.ts";
import { callOrchestrator, relayError, type Upstream, UpstreamFailure } from "./orchestrator.ts";
import { clearedSessionCookie, isPlausibleToken, readSessionToken, sessionCookie, sessionEndedCookie } from "./session.ts";

export type Deps = Upstream & { config: ServerConfig };

const CONVERSATION_ID = /^conv-[0-9a-f]{32}$/;
// Loose outer bounds only, to cap what this server buffers; the orchestrator enforces
// the real limits (its default message limit is much lower) and its 422 is relayed.
const MAX_TITLE_CHARS = 200;
const MAX_MESSAGE_CHARS = 200_000;
const SMALL_BODY_BYTES = 8 * 1024;
const MESSAGE_BODY_BYTES = 1024 * 1024;
// The orchestrator's MAX_PAGE_SIZE (services/orchestrator/app/api/v1/pagination.py).
export const PAGE_SIZE = 100;
const MAX_OFFSET = 1_000_000_000;

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-store, no-transform",
  "X-Accel-Buffering": "no",
};

function signedOut(): Response {
  return errorResponse(401, "SIGNED_OUT", "Sign in to continue.", {
    "Set-Cookie": clearedSessionCookie(),
  });
}

// The orchestrator rejected the session: clear it and leave the "session ended" marker.
function sessionRejected(): Response {
  const headers = new Headers();
  headers.append("Set-Cookie", clearedSessionCookie());
  headers.append("Set-Cookie", sessionEndedCookie());
  return errorResponse(401, "UNAUTHENTICATED", "Your session has ended. Sign in again.", headers);
}

function tooLarge(): Response {
  return errorResponse(413, "BODY_TOO_LARGE", "That request is too large.");
}

function badConversationId(): Response {
  return errorResponse(404, "CONVERSATION_NOT_FOUND", "That conversation doesn't exist.");
}

function validationFailed(field: string, message: string): Response {
  return jsonResponse(
    { error: { code: "VALIDATION_FAILED", message: "Request validation failed.", fields: { [field]: message } } },
    422,
  );
}

function guarded(request: Request, deps: Deps, withBody: boolean): Response | null {
  return rejectCrossSite(request, deps.config.webOrigin) ?? (withBody ? rejectNonJson(request) : null);
}

async function forwardJson(
  deps: Deps,
  call: Parameters<typeof callOrchestrator>[1],
  successStatus: number,
): Promise<Response> {
  let response: Response;
  try {
    response = await callOrchestrator(deps, call);
  } catch (error) {
    if (error instanceof UpstreamFailure) return error.response;
    throw error;
  }
  if (!response.ok) return relayError(response);
  return jsonResponse(await response.json(), successStatus);
}

// Username and password go to the orchestrator once; only the session token it returns
// is kept, in the httpOnly cookie. The password is never stored or logged here.
export async function signIn(request: Request, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, true);
  if (rejected) return rejected;
  const body = await readJsonBody(request, SMALL_BODY_BYTES);
  if (body === BODY_TOO_LARGE) return tooLarge();
  const fields = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const { username, password } = fields;
  if (typeof username !== "string" || !username.trim() || username.length > 64) {
    return validationFailed("username", "Enter your username.");
  }
  if (typeof password !== "string" || !password || password.length > 256) {
    return validationFailed("password", "Enter your password.");
  }
  let response: Response;
  try {
    response = await callOrchestrator(deps, {
      method: "POST",
      path: "/v1/sessions",
      token: null,
      body: { username, password },
      signal: request.signal,
    });
  } catch (error) {
    if (error instanceof UpstreamFailure) return error.response;
    throw error;
  }
  if (!response.ok) return relayError(response, false);
  const session = (await response.json().catch(() => null)) as { session_token?: unknown; expires_at?: unknown } | null;
  const expiresAt = typeof session?.expires_at === "string" ? Date.parse(session.expires_at) : NaN;
  const lifetimeSeconds = (expiresAt - Date.now()) / 1000;
  // A cookie with no lifetime would be dropped silently (a clock far ahead of the
  // orchestrator's), leaving the user stuck on sign-in with no error.
  if (!isPlausibleToken(session?.session_token) || !(lifetimeSeconds >= 1)) {
    return errorResponse(502, "ORCHESTRATOR_ERROR", "The GreenLoop server sent an unexpected reply.");
  }
  return emptyResponse(204, { "Set-Cookie": sessionCookie(session.session_token, lifetimeSeconds) });
}

// Who is signed in (username for the user menu). Only these fields pass through.
export async function currentSession(request: Request, deps: Deps): Promise<Response> {
  const token = readSessionToken(request);
  if (!token) return signedOut();
  let response: Response;
  try {
    response = await callOrchestrator(deps, { method: "GET", path: "/v1/sessions/current", token, signal: request.signal });
  } catch (error) {
    if (error instanceof UpstreamFailure) return error.response;
    throw error;
  }
  if (!response.ok) return relayError(response);
  const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  const { username, display_name: displayName, expires_at: expiresAt } = body ?? {};
  if (typeof username !== "string" || typeof displayName !== "string" || typeof expiresAt !== "string") {
    return errorResponse(502, "ORCHESTRATOR_ERROR", "The GreenLoop server sent an unexpected reply.");
  }
  return jsonResponse({ username, display_name: displayName, expires_at: expiresAt });
}

// Revokes the server-side session (or every session with ?scope=all), then clears the
// cookie whatever the orchestrator says, so the browser is signed out either way.
export async function signOut(request: Request, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, false);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  const everywhere = new URL(request.url).searchParams.get("scope") === "all";
  const cleared = { "Set-Cookie": clearedSessionCookie() };
  if (!token) return emptyResponse(204, cleared);
  try {
    const response = await callOrchestrator(deps, {
      method: "DELETE",
      path: everywhere ? "/v1/sessions" : "/v1/sessions/current",
      token,
      signal: request.signal,
    });
    if (everywhere && !response.ok && response.status !== 401) {
      const failure = await relayError(response);
      failure.headers.set("Set-Cookie", clearedSessionCookie());
      return failure;
    }
  } catch (error) {
    if (!(error instanceof UpstreamFailure)) throw error;
    if (everywhere) {
      error.response.headers.set("Set-Cookie", clearedSessionCookie());
      return error.response;
    }
  }
  return emptyResponse(204, cleared);
}

export async function listConversations(request: Request, deps: Deps): Promise<Response> {
  const token = readSessionToken(request);
  if (!token) return signedOut();
  return forwardJson(
    deps,
    { method: "GET", path: `/v1/conversations?limit=${PAGE_SIZE}`, token, signal: request.signal },
    200,
  );
}

export async function createConversation(request: Request, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, true);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  if (!token) return signedOut();
  const body = await readJsonBody(request, SMALL_BODY_BYTES);
  if (body === BODY_TOO_LARGE) return tooLarge();
  const title = typeof body === "object" && body !== null ? (body as { title?: unknown }).title : undefined;
  if (title !== undefined && (typeof title !== "string" || !title.trim() || title.length > MAX_TITLE_CHARS)) {
    return validationFailed("title", `Use 1 to ${MAX_TITLE_CHARS} characters.`);
  }
  return forwardJson(
    deps,
    { method: "POST", path: "/v1/conversations", token, body: title === undefined ? {} : { title }, signal: request.signal },
    201,
  );
}

export async function listMessages(request: Request, conversationId: string, deps: Deps): Promise<Response> {
  const token = readSessionToken(request);
  if (!token) return signedOut();
  if (!CONVERSATION_ID.test(conversationId)) return badConversationId();
  const offsetParam = new URL(request.url).searchParams.get("offset") ?? "0";
  const offset = /^\d{1,10}$/.test(offsetParam) ? Number(offsetParam) : NaN;
  if (!(offset <= MAX_OFFSET)) return validationFailed("offset", "Use a whole number of 0 or more.");
  return forwardJson(
    deps,
    {
      method: "GET",
      path: `/v1/conversations/${conversationId}/messages?limit=${PAGE_SIZE}&offset=${offset}`,
      token,
      signal: request.signal,
    },
    200,
  );
}

// Streams the orchestrator's SSE body through unchanged. Errors before the stream
// starts come back as JSON; errors during it arrive as the orchestrator's `error` event.
export async function sendMessage(request: Request, conversationId: string, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, true);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  if (!token) return signedOut();
  if (!CONVERSATION_ID.test(conversationId)) return badConversationId();
  const body = await readJsonBody(request, MESSAGE_BODY_BYTES);
  if (body === BODY_TOO_LARGE) return tooLarge();
  const content = typeof body === "object" && body !== null ? (body as { content?: unknown }).content : undefined;
  if (typeof content !== "string" || !content.trim() || content.length > MAX_MESSAGE_CHARS) {
    return validationFailed("content", "Write a message first.");
  }
  let response: Response;
  try {
    response = await callOrchestrator(deps, {
      method: "POST",
      path: `/v1/conversations/${conversationId}/messages`,
      token,
      body: { content },
      stream: true,
      signal: request.signal,
    });
  } catch (error) {
    if (error instanceof UpstreamFailure) return error.response;
    throw error;
  }
  if (!response.ok) return relayError(response);
  if (!response.body || !(response.headers.get("content-type") ?? "").startsWith("text/event-stream")) {
    // Not awaited: cancelling must not hold up the error reply.
    void response.body?.cancel().catch(() => undefined);
    return errorResponse(502, "ORCHESTRATOR_ERROR", "The GreenLoop server sent an unexpected reply.");
  }
  return new Response(response.body, { status: 200, headers: SSE_HEADERS });
}

const MESSAGE_ID = /^msg-[0-9a-f]{32}$/;

// "Remember this": saves one message of the user's own conversation as memory.
export async function rememberMessage(
  request: Request,
  conversationId: string,
  messageId: string,
  deps: Deps,
): Promise<Response> {
  const rejected = guarded(request, deps, true);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  if (!token) return signedOut();
  if (!CONVERSATION_ID.test(conversationId) || !MESSAGE_ID.test(messageId)) {
    return errorResponse(404, "MESSAGE_NOT_FOUND", "That message doesn't exist.");
  }
  const body = await readJsonBody(request, SMALL_BODY_BYTES);
  if (body === BODY_TOO_LARGE) return tooLarge();
  return forwardJson(
    deps,
    {
      method: "POST",
      path: `/v1/conversations/${conversationId}/messages/${messageId}/remember`,
      token,
      body: {},
      signal: request.signal,
    },
    201,
  );
}

// User records are mem-<32 hex>; execution records written by dispatches are mem-exec-<32 hex>
// (services/orchestrator/app/memory/execution.py).
const MEMORY_ID = /^mem-(?:exec-)?[0-9a-f]{32}$/;
const MAX_QUERY_CHARS = 200;
const MAX_MEMORY_CHARS = 20_000;
const MEMORY_CATEGORIES = new Set([
  "general_knowledge",
  "project_context",
  "task_execution_history",
  "user_context",
  "organization_context",
  "decision",
  "verified_outcome",
  "correction",
  "agent_performance",
]);

function memoryNotFound(): Response {
  return errorResponse(404, "MEMORY_RECORD_NOT_FOUND", "That memory doesn't exist.");
}

function offsetFrom(request: Request): number | null {
  const value = new URL(request.url).searchParams.get("offset") ?? "0";
  return /^\d{1,10}$/.test(value) && Number(value) <= MAX_OFFSET ? Number(value) : null;
}

// Live memory, newest first, optionally filtered by text. Only q and offset pass through.
export async function listMemory(request: Request, deps: Deps): Promise<Response> {
  const token = readSessionToken(request);
  if (!token) return signedOut();
  const offset = offsetFrom(request);
  if (offset === null) return validationFailed("offset", "Use a whole number of 0 or more.");
  const query = (new URL(request.url).searchParams.get("q") ?? "").trim();
  if (query.length > MAX_QUERY_CHARS) return validationFailed("q", `Search with at most ${MAX_QUERY_CHARS} characters.`);
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (query) params.set("q", query);
  return forwardJson(deps, { method: "GET", path: `/v1/memory-records?${params}`, token, signal: request.signal }, 200);
}

export async function memoryHistory(request: Request, recordId: string, deps: Deps): Promise<Response> {
  const token = readSessionToken(request);
  if (!token) return signedOut();
  if (!MEMORY_ID.test(recordId)) return memoryNotFound();
  return forwardJson(
    deps,
    { method: "GET", path: `/v1/memory-records/${recordId}/history`, token, signal: request.signal },
    200,
  );
}

// Correct (content only, marks it corrected) or supersede (content and optionally category).
// Confidence is never taken from the browser: only system principals may verify memory.
export async function reviseMemory(request: Request, recordId: string, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, true);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  if (!token) return signedOut();
  if (!MEMORY_ID.test(recordId)) return memoryNotFound();
  const body = await readJsonBody(request, MESSAGE_BODY_BYTES);
  if (body === BODY_TOO_LARGE) return tooLarge();
  const fields = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const { operation, content, category } = fields;
  if (operation !== "correct" && operation !== "supersede") {
    return validationFailed("operation", "Choose correct or supersede.");
  }
  if (typeof content !== "string" || !content.trim() || content.length > MAX_MEMORY_CHARS) {
    return validationFailed("content", `Use 1 to ${MAX_MEMORY_CHARS} characters.`);
  }
  if (category !== undefined && (operation !== "supersede" || typeof category !== "string" || !MEMORY_CATEGORIES.has(category))) {
    return validationFailed("category", "Choose a known category; only a supersede can change it.");
  }
  return forwardJson(
    deps,
    {
      method: "POST",
      path: `/v1/memory-records/${recordId}/revisions`,
      token,
      body: category === undefined ? { operation, content } : { operation, content, category },
      signal: request.signal,
    },
    201,
  );
}

// Delete is a tombstone: the chain stops being retrieved, its history remains (ADR 0011).
export async function deleteMemory(request: Request, recordId: string, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, false);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  if (!token) return signedOut();
  if (!MEMORY_ID.test(recordId)) return memoryNotFound();
  let response: Response;
  try {
    response = await callOrchestrator(deps, {
      method: "DELETE",
      path: `/v1/memory-records/${recordId}`,
      token,
      signal: request.signal,
    });
  } catch (error) {
    if (error instanceof UpstreamFailure) return error.response;
    throw error;
  }
  if (!response.ok) return relayError(response);
  return emptyResponse(204);
}

const PLAN_ID = /^plan-[0-9a-f]{32}$/;
const MAX_GOAL_CHARS = 2000;
// Drafting answers only when the model is done; the orchestrator's own AI timeout is 120 s.
export const PLAN_TIMEOUT_MS = 150_000;

// Drafts a plan (stored as a draft; nothing runs). Only goal and conversation_id pass through.
export async function draftPlan(request: Request, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, true);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  if (!token) return signedOut();
  const body = await readJsonBody(request, SMALL_BODY_BYTES);
  if (body === BODY_TOO_LARGE) return tooLarge();
  const fields = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const { goal, conversation_id: conversationId } = fields;
  if (typeof goal !== "string" || !goal.trim() || goal.length > MAX_GOAL_CHARS) {
    return validationFailed("goal", `Describe the goal in 1 to ${MAX_GOAL_CHARS} characters.`);
  }
  if (conversationId !== undefined && (typeof conversationId !== "string" || !CONVERSATION_ID.test(conversationId))) {
    return badConversationId();
  }
  return forwardJson(
    deps,
    {
      method: "POST",
      path: "/v1/plans",
      token,
      body: conversationId === undefined ? { goal } : { goal, conversation_id: conversationId },
      signal: request.signal,
      timeoutMs: PLAN_TIMEOUT_MS,
    },
    201,
  );
}

export async function listPlans(request: Request, deps: Deps): Promise<Response> {
  const token = readSessionToken(request);
  if (!token) return signedOut();
  return forwardJson(deps, { method: "GET", path: `/v1/plans?limit=${PAGE_SIZE}`, token, signal: request.signal }, 200);
}

export async function discardPlan(request: Request, planId: string, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, false);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  if (!token) return signedOut();
  if (!PLAN_ID.test(planId)) return errorResponse(404, "PLAN_NOT_FOUND", "That plan doesn't exist.");
  let response: Response;
  try {
    response = await callOrchestrator(deps, { method: "DELETE", path: `/v1/plans/${planId}`, token, signal: request.signal });
  } catch (error) {
    if (error instanceof UpstreamFailure) return error.response;
    throw error;
  }
  if (!response.ok) return relayError(response);
  return emptyResponse(204);
}

// Counts for the HUD's KPI tiles, from the orchestrator's own list endpoints only. A tile
// whose source fails, or doesn't exist yet, gets value null and a note; never a guess.
type Tile = { value: number | null; note: string | null };

const OVERVIEW_SOURCES: Record<string, string> = {
  conversations: "/v1/conversations?limit=1",
  memories: "/v1/memory-records?limit=1",
  plan_drafts: "/v1/plans?status=draft&limit=1",
  pending_approvals: "/v1/approvals?status=pending&limit=1",
  agents: "/v1/agents?limit=1",
};

async function countFrom(deps: Deps, token: string, path: string, signal: AbortSignal): Promise<Tile | "signed-out"> {
  try {
    const response = await callOrchestrator(deps, { method: "GET", path, token, signal });
    if (response.status === 401) return "signed-out";
    if (!response.ok) {
      void response.body?.cancel().catch(() => undefined);
      return { value: null, note: "Unavailable right now" };
    }
    const total = ((await response.json().catch(() => null)) as { meta?: { total?: unknown } } | null)?.meta?.total;
    return Number.isInteger(total) && (total as number) >= 0
      ? { value: total as number, note: null }
      : { value: null, note: "Unavailable right now" };
  } catch (error) {
    if (error instanceof UpstreamFailure) return { value: null, note: "Unavailable right now" };
    throw error;
  }
}

export async function overview(request: Request, deps: Deps): Promise<Response> {
  const token = readSessionToken(request);
  if (!token) return signedOut();
  const names = Object.keys(OVERVIEW_SOURCES);
  const results = await Promise.all(names.map((name) => countFrom(deps, token, OVERVIEW_SOURCES[name], request.signal)));
  if (results.includes("signed-out")) return sessionRejected();
  return jsonResponse({
    tiles: Object.fromEntries(names.map((name, index) => [name, results[index]])),
    updated_at: new Date().toISOString(),
  });
}

// Health of the three services behind the web server, as statuses only. The orchestrator is
// up if it answers its readiness check at all; broker and database come from that check.
const HEALTH_STATUSES = new Set(["ok", "unavailable", "not_configured"]);

export async function health(request: Request, deps: Deps): Promise<Response> {
  if (!readSessionToken(request)) return signedOut();
  let checks: Record<string, unknown> = {};
  let orchestrator = "unavailable";
  try {
    const response = await callOrchestrator(deps, { method: "GET", path: "/v1/health", token: null, signal: request.signal, timeoutMs: 5000 });
    if (response.status === 200 || response.status === 503) {
      orchestrator = "ok";
      checks = (((await response.json().catch(() => null)) as { checks?: Record<string, unknown> } | null)?.checks ?? {});
    } else {
      void response.body?.cancel().catch(() => undefined);
    }
  } catch (error) {
    if (!(error instanceof UpstreamFailure)) throw error;
  }
  const status = (value: unknown) =>
    orchestrator !== "ok" ? "unknown" : typeof value === "string" && HEALTH_STATUSES.has(value) ? value : "unknown";
  const services = [
    { name: "orchestrator", status: orchestrator },
    { name: "broker", status: status(checks.broker) },
    { name: "database", status: status(checks.database) },
  ];
  return jsonResponse({
    services,
    up: services.filter((service) => service.status === "ok").length,
    total: services.length,
    updated_at: new Date().toISOString(),
  });
}
