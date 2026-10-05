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

export const BODY_TOO_LARGE = Symbol("body too large");

// Reads at most maxBytes before giving up, so an oversized body is never buffered.
// Returns undefined for anything that isn't valid JSON.
export async function readJsonBody(request: Request, maxBytes: number): Promise<unknown> {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > maxBytes) return BODY_TOO_LARGE;
  if (!request.body) return undefined;
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        return BODY_TOO_LARGE;
      }
      text += decoder.decode(value, { stream: true });
    }
  } catch {
    // The client went away mid-upload.
    return undefined;
  }
  try {
    return JSON.parse(text + decoder.decode());
  } catch {
    return undefined;
  }
}
