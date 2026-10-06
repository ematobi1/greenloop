// Browser-side calls to this app's own /api routes. Same origin only: the browser
// never learns the orchestrator's address or the token.
//
// The shapes below mirror ConversationOut, MessageOut and the SSE events in
// services/orchestrator/app/api/v1/chat.py, which is the source of truth (ADR 0010).

import type { ApiFailure } from "./errors.ts";
import { createSseParser } from "./sse.ts";

export type Conversation = { conversation_id: string; title: string; created_at: string; updated_at: string };

export type Message = {
  message_id: string;
  conversation_id: string;
  sequence: number;
  role: string;
  content: string;
  status: string;
  created_at: string;
};

export class ApiError extends Error {
  readonly failure: ApiFailure;

  constructor(failure: ApiFailure) {
    super(failure.code);
    this.failure = failure;
  }
}

const JSON_HEADERS = { "Content-Type": "application/json" };

async function failureFrom(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    if (typeof body?.error?.code === "string") {
      return new ApiError({ status: response.status, code: body.error.code, message: String(body.error.message ?? "") });
    }
  } catch {
    // Fall through to a generic failure.
  }
  return new ApiError({ status: response.status, code: "UNEXPECTED", message: "" });
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, credentials: "same-origin", cache: "no-store" });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError({ status: 0, code: "NETWORK", message: "" });
  }
  if (!response.ok) throw await failureFrom(response);
  return response;
}

export async function signIn(username: string, password: string): Promise<void> {
  await send("/api/session", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ username, password }),
  });
}

// `everywhere` also ends the user's sessions on every other device.
export async function signOut(everywhere = false): Promise<void> {
  await send(everywhere ? "/api/session?scope=all" : "/api/session", { method: "DELETE" });
}

type Page<T> = { data: T[]; meta: { total: number; limit: number; offset: number } };

// The orchestrator returns at most 100 rows per page, newest conversations first.
export async function listConversations(): Promise<{ conversations: Conversation[]; total: number }> {
  const page: Page<Conversation> = await (await send("/api/conversations")).json();
  return { conversations: page.data, total: page.meta.total };
}

export async function createConversation(): Promise<Conversation> {
  return (await send("/api/conversations", { method: "POST", headers: JSON_HEADERS, body: "{}" })).json();
}

// Messages come oldest first, 100 per page. A long conversation shows its latest page;
// `hidden` counts the earlier messages left out.
export async function listMessages(conversationId: string): Promise<{ messages: Message[]; hidden: number }> {
  const path = `/api/conversations/${encodeURIComponent(conversationId)}/messages`;
  let page: Page<Message> = await (await send(path)).json();
  if (page.meta.total > page.data.length) {
    const offset = Math.max(page.meta.total - page.meta.limit, 0);
    page = await (await send(`${path}?offset=${offset}`)).json();
  }
  return { messages: page.data, hidden: page.meta.offset };
}

// "Remember this": saves one message as private, unverified memory.
export async function rememberMessage(conversationId: string, messageId: string): Promise<void> {
  const path = `/api/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/remember`;
  await send(path, { method: "POST", headers: JSON_HEADERS, body: "{}" });
}

export type StreamHandlers = {
  onUserMessage: (message: Message) => void;
  onDelta: (text: string) => void;
  onDone: (message: Message) => void;
  onError: (failure: ApiFailure, partial: Message | null) => void;
};

// Resolves when the stream ends. Errors before the stream starts throw ApiError;
// errors inside it arrive through onError, as does a stream that ends without `done`.
export async function streamMessage(
  conversationId: string,
  content: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await send(`/api/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ content }),
    signal,
  });
  let finished = false;
  const parser = createSseParser(({ event, data }) => {
    let payload;
    try {
      payload = JSON.parse(data);
    } catch {
      return;
    }
    if (event === "message" && payload.user_message) handlers.onUserMessage(payload.user_message);
    else if (event === "delta" && typeof payload.text === "string") handlers.onDelta(payload.text);
    else if (event === "done" && payload.assistant_message) {
      finished = true;
      handlers.onDone(payload.assistant_message);
    } else if (event === "error") {
      finished = true;
      handlers.onError(
        { status: 200, code: String(payload.error?.code ?? "UNEXPECTED"), message: String(payload.error?.message ?? "") },
        payload.partial_message ?? null,
      );
    }
  });
  const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      parser.push(value);
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
  }
  parser.end();
  if (!finished) handlers.onError({ status: 0, code: "NETWORK", message: "" }, null);
}
