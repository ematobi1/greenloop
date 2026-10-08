// JSON responses in the API rules' error shape. Nothing here echoes request data.

export type ErrorBody = {
  error: { code: string; message: string; fields?: Record<string, string> };
};

const NO_STORE = { "Cache-Control": "no-store" };

// Headers objects keep repeated Set-Cookie values; spreading them into an object would not.
export function jsonResponse(body: unknown, status = 200, headers: HeadersInit = {}): Response {
  const merged = new Headers(headers);
  merged.set("Cache-Control", NO_STORE["Cache-Control"]);
  return Response.json(body, { status, headers: merged });
}

export function errorResponse(
  status: number,
  code: string,
  message: string,
  headers: HeadersInit = {},
): Response {
  const body: ErrorBody = { error: { code, message } };
  return jsonResponse(body, status, headers);
}

export function emptyResponse(status: number, headers: HeadersInit = {}): Response {
  const merged = new Headers(headers);
  merged.set("Cache-Control", NO_STORE["Cache-Control"]);
  return new Response(null, { status, headers: merged });
}

// Keeps only the documented error fields, as strings, so an upstream body can't smuggle
// anything else through the proxy.
export function sanitizeErrorBody(body: unknown): ErrorBody | null {
  if (typeof body !== "object" || body === null) return null;
  const error = (body as { error?: unknown }).error;
  if (typeof error !== "object" || error === null) return null;
  const { code, message, fields } = error as Record<string, unknown>;
  if (typeof code !== "string" || typeof message !== "string") return null;
  const clean: ErrorBody = { error: { code, message } };
  if (typeof fields === "object" && fields !== null) {
    clean.error.fields = Object.fromEntries(
      Object.entries(fields).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
    );
  }
  return clean;
}
