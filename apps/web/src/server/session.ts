// The web session token (from username and password sign-in, ADR 0012) lives only in this cookie. httpOnly keeps it from page scripts, Secure
// and the __Host- prefix keep it on this origin over a secure context (browsers treat
// localhost and 127.0.0.1 as secure), SameSite=Strict keeps it off cross-site requests.
// Max-Age, not a session cookie: browsers restore session cookies with the session.

export const SESSION_COOKIE = "__Host-greenloop_session";
export const SESSION_MAX_AGE_SECONDS = 12 * 60 * 60;

const TOKEN_PATTERN = /^[\x21-\x7e]{1,512}$/;
const UNSAFE_IN_COOKIE = /[;,"\\]/;

export function isPlausibleToken(token: unknown): token is string {
  return typeof token === "string" && TOKEN_PATTERN.test(token) && !UNSAFE_IN_COOKIE.test(token);
}

// maxAgeSeconds lets the cookie end no later than the server-side session does.
export function sessionCookie(token: string, maxAgeSeconds = SESSION_MAX_AGE_SECONDS): string {
  if (!isPlausibleToken(token)) throw new Error("Refusing to store a malformed token.");
  const maxAge = Math.max(0, Math.min(SESSION_MAX_AGE_SECONDS, Math.floor(maxAgeSeconds)));
  return `${SESSION_COOKIE}=${token}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Strict`;
}

export function clearedSessionCookie(): string {
  return `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`;
}

export function readSessionToken(request: Request): string | null {
  const header = request.headers.get("cookie");
  if (!header) return null;
  for (const part of header.split(";")) {
    const separator = part.indexOf("=");
    if (separator === -1) continue;
    if (part.slice(0, separator).trim() !== SESSION_COOKIE) continue;
    const value = part.slice(separator + 1).trim();
    return isPlausibleToken(value) ? value : null;
  }
  return null;
}
