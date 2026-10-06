// The only place the web server talks to the orchestrator. The token goes in the
// Authorization header of the outbound call and nowhere else.

import type { ServerConfig } from "./config.ts";
import { errorResponse, jsonResponse, sanitizeErrorBody } from "./http.ts";
import { clearedSessionCookie } from "./session.ts";

export type Upstream = {
  config: ServerConfig;
  fetch: typeof fetch;
  timeoutMs: number;
};

export type UpstreamCall = {
  method: "GET" | "POST" | "DELETE";
  path: string;
  token: string | null;
  body?: unknown;
  stream?: boolean;
  signal?: AbortSignal;
};

export const DEFAULT_TIMEOUT_MS = 10_000;

export class UpstreamFailure extends Error {
  readonly response: Response;

  constructor(response: Response) {
    super("Orchestrator call failed");
    this.response = response;
  }
}

// The timeout covers the response headers only: a streamed reply may run longer.
// An aborted client request aborts the outbound call too, so the orchestrator stops.
export async function callOrchestrator(upstream: Upstream, call: UpstreamCall): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), upstream.timeoutMs);
  const forwardAbort = () => controller.abort("client");
  call.signal?.addEventListener("abort", forwardAbort, { once: true });
  const headers: Record<string, string> = {
    Accept: call.stream ? "text/event-stream" : "application/json",
  };
  if (call.token !== null) headers.Authorization = `Bearer ${call.token}`;
  if (call.body !== undefined) headers["Content-Type"] = "application/json";
  try {
    return await upstream.fetch(`${upstream.config.orchestratorUrl}${call.path}`, {
      method: call.method,
      headers,
      body: call.body === undefined ? undefined : JSON.stringify(call.body),
      signal: controller.signal,
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    call.signal?.removeEventListener("abort", forwardAbort);
    if (controller.signal.reason === "timeout") {
      throw new UpstreamFailure(
        errorResponse(504, "ORCHESTRATOR_TIMEOUT", "The GreenLoop server took too long to answer."),
      );
    }
    throw new UpstreamFailure(
      errorResponse(502, "ORCHESTRATOR_UNAVAILABLE", "The GreenLoop server can't be reached."),
    );
  } finally {
    clearTimeout(timer);
  }
}

// Passes an orchestrator error on with only its documented fields. A 401 also clears
// the session cookie, so the browser goes back to sign-in.
export async function relayError(response: Response): Promise<Response> {
  const headers: Record<string, string> = response.status === 401 ? { "Set-Cookie": clearedSessionCookie() } : {};
  const retryAfter = response.headers.get("retry-after");
  if (response.status === 429 && retryAfter && /^\d{1,6}$/.test(retryAfter)) headers["Retry-After"] = retryAfter;
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  const clean = sanitizeErrorBody(body);
  if (clean === null) {
    return errorResponse(502, "ORCHESTRATOR_ERROR", "The GreenLoop server sent an unexpected reply.", headers);
  }
  return jsonResponse(clean, response.status, headers);
}
