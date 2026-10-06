// What the chat UI tells the user for each error code. Server messages are never shown
// as-is for these codes, so the wording stays ours.

export type ApiFailure = { status: number; code: string; message: string };

const MESSAGES: Record<string, string> = {
  CONVERSATION_BUSY: "A reply is still being written in this conversation. Wait for it to finish, then send again.",
  AI_NOT_CONFIGURED: "No AI provider is configured on the GreenLoop server, so it can't reply yet. Ask the admin to set one up.",
  INVALID_CREDENTIALS: "Wrong username or password.",
  SIGN_IN_THROTTLED: "Too many sign-in attempts. Wait a few minutes, then try again.",
  SIGNED_OUT: "Your session has ended. Sign in again.",
  UNAUTHENTICATED: "Your session has ended. Sign in again.",
  CONVERSATION_NOT_FOUND: "This conversation no longer exists.",
  ALREADY_REMEMBERED: "That message is already saved to memory.",
  MESSAGE_INCOMPLETE: "Only a complete message can be saved to memory.",
  MESSAGE_NOT_FOUND: "That message no longer exists.",
  PLAN_DRAFT_INVALID: "The model didn't return a usable plan. Try again, or rephrase the goal.",
  PLAN_NOT_FOUND: "That plan no longer exists.",
  MEMORY_RECORD_NOT_FOUND: "That memory no longer exists. Refresh the list.",
  MEMORY_RECORD_CONFLICT: "This memory changed since you opened it. Refresh, then edit the latest version.",
  ORCHESTRATOR_UNAVAILABLE: "The GreenLoop server can't be reached. Try again in a moment.",
  ORCHESTRATOR_TIMEOUT: "The GreenLoop server took too long to answer. Try again.",
  CROSS_SITE_REQUEST: "This request was blocked. Reload the page and try again.",
  NETWORK: "You seem to be offline. Check your connection and try again.",
};

export const GENERIC_ERROR = "Something went wrong. Try again.";

export function isSignedOut(failure: ApiFailure): boolean {
  return failure.status === 401;
}

export function messageFor(failure: ApiFailure): string {
  return MESSAGES[failure.code] ?? (failure.status === 401 ? MESSAGES.SIGNED_OUT : GENERIC_ERROR);
}
