// Cross-site request protection on top of SameSite=Strict: a state-changing request
// must come from WEB_ORIGIN (the configured value, never the incoming Host header) and,
// when it has a body, be JSON, which a plain HTML form can't send.

import { errorResponse } from "./http.ts";

export function rejectCrossSite(request: Request, webOrigin: string): Response | null {
  if (request.headers.get("origin") !== webOrigin) {
    return errorResponse(403, "CROSS_SITE_REQUEST", "This request must come from the GreenLoop app.");
  }
  return null;
}

export function rejectNonJson(request: Request): Response | null {
  const type = request.headers.get("content-type") ?? "";
  if (type.split(";")[0].trim().toLowerCase() !== "application/json") {
    return errorResponse(415, "UNSUPPORTED_MEDIA_TYPE", "Send the request body as JSON.");
  }
  return null;
}

export async function readJsonBody(request: Request): Promise<unknown> {
  try {
    return await request.json();
  } catch {
    return undefined;
  }
}
