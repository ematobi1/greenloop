// Request handlers behind the app/api route files, kept free of Next imports so the
// tests can call them with plain Request objects. Only these paths reach the
// orchestrator; there is no catch-all proxy.

import type { ServerConfig } from "./config.ts";
import { readJsonBody, rejectCrossSite, rejectNonJson } from "./guard.ts";
import { emptyResponse, errorResponse, jsonResponse } from "./http.ts";
import { callOrchestrator, relayError, type Upstream, UpstreamFailure } from "./orchestrator.ts";
import { clearedSessionCookie, isPlausibleToken, readSessionToken, sessionCookie } from "./session.ts";

export type Deps = Upstream & { config: ServerConfig };

const CONVERSATION_ID = /^conv-[0-9a-f]{32}$/;
const MAX_TITLE_CHARS = 200;
const MAX_MESSAGE_CHARS = 200_000;

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-store",
  "X-Accel-Buffering": "no",
};

function signedOut(): Response {
  return errorResponse(401, "SIGNED_OUT", "Sign in with your GreenLoop API token.", {
    "Set-Cookie": clearedSessionCookie(),
  });
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

export function sessionStatus(request: Request): Response {
  return jsonResponse({ signed_in: readSessionToken(request) !== null });
}

export async function signIn(request: Request, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, true);
  if (rejected) return rejected;
  const body = await readJsonBody(request);
  const token = typeof body === "object" && body !== null ? (body as { token?: unknown }).token : undefined;
  if (!isPlausibleToken(token)) {
    return validationFailed("token", "Paste the API token exactly as issued.");
  }
  let response: Response;
  try {
    response = await callOrchestrator(deps, {
      method: "GET",
      path: "/v1/conversations?limit=1",
      token,
      signal: request.signal,
    });
  } catch (error) {
    if (error instanceof UpstreamFailure) return error.response;
    throw error;
  }
  if (response.status === 401) {
    return errorResponse(401, "INVALID_TOKEN", "That token isn't valid. Check it and try again.");
  }
  if (!response.ok) return relayError(response);
  return emptyResponse(204, { "Set-Cookie": sessionCookie(token) });
}

export async function signOut(request: Request, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, false);
  if (rejected) return rejected;
  return emptyResponse(204, { "Set-Cookie": clearedSessionCookie() });
}

export async function listConversations(request: Request, deps: Deps): Promise<Response> {
  const token = readSessionToken(request);
  if (!token) return signedOut();
  return forwardJson(
    deps,
    { method: "GET", path: "/v1/conversations?limit=100", token, signal: request.signal },
    200,
  );
}

export async function createConversation(request: Request, deps: Deps): Promise<Response> {
  const rejected = guarded(request, deps, true);
  if (rejected) return rejected;
  const token = readSessionToken(request);
  if (!token) return signedOut();
  const body = await readJsonBody(request);
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
  return forwardJson(
    deps,
    { method: "GET", path: `/v1/conversations/${conversationId}/messages?limit=500`, token, signal: request.signal },
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
  const body = await readJsonBody(request);
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
