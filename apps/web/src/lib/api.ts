// Browser-side calls to this app's own /api routes. Same origin only: the browser
// never learns the orchestrator's address or the token.

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

export async function signIn(token: string): Promise<void> {
  await send("/api/session", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ token }) });
}

export async function signOut(): Promise<void> {
  await send("/api/session", { method: "DELETE" });
}

export async function listConversations(): Promise<Conversation[]> {
  return (await (await send("/api/conversations")).json()).data;
}

export async function createConversation(): Promise<Conversation> {
  return (await send("/api/conversations", { method: "POST", headers: JSON_HEADERS, body: "{}" })).json();
}

export async function listMessages(conversationId: string): Promise<Message[]> {
  return (await (await send(`/api/conversations/${encodeURIComponent(conversationId)}/messages`)).json()).data;
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
