// A stand-in orchestrator for the end-to-end test: the real API's paths, status codes,
// error envelope and SSE events, with canned replies chosen by the message text.

import { createServer } from "node:http";

export const E2E_TOKEN = "gls_e2e-synthetic-session_9f8e7d6c5b4a";
export const E2E_USERNAME = "alice";
export const E2E_PASSWORD = "correct horse battery staple";

const CONV_PREFIX = "conv-";
// The real orchestrator's MAX_PAGE_SIZE; larger limits get its 422.
const MAX_PAGE_SIZE = 100;
const SSE_HEADERS = { "Content-Type": "text/event-stream", "Cache-Control": "no-store" };

export function startMockOrchestrator(port) {
  const sessions = new Set();
  let nextId = 1;
  const conversations = [];
  const messages = new Map();
  const remembered = new Set();

  const json = (response, status, body) => {
    response.writeHead(status, { "Content-Type": "application/json" });
    response.end(JSON.stringify(body));
  };
  const fail = (response, status, code, message) => json(response, status, { error: { code, message } });
  const now = () => new Date().toISOString();
  const sse = (response, event, data) => response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

  function message(conversationId, role, content, status = "complete") {
    const list = messages.get(conversationId);
    const row = {
      message_id: `msg-${String(nextId++).padStart(32, "0")}`,
      conversation_id: conversationId,
      sequence: list.length + 1,
      role,
      content,
      status,
      provider: "mock",
      model: "mock",
      created_at: now(),
    };
    list.push(row);
    return row;
  }

  async function reply(response, conversationId, content) {
    if (content === "busy") return fail(response, 409, "CONVERSATION_BUSY", "busy");
    if (content === "no ai") return fail(response, 503, "AI_NOT_CONFIGURED", "not configured");
    response.writeHead(200, SSE_HEADERS);
    sse(response, "message", { user_message: message(conversationId, "user", content) });
    const parts =
      content === "html please"
        ? ['<img src=x onerror="window.__pwned=1">', "<script>window.__pwned=2</script>"]
        : ["Hello", " from", " GreenLoop"];
    for (const part of parts) {
      sse(response, "delta", { text: part });
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    sse(response, "done", { assistant_message: message(conversationId, "assistant", parts.join("")) });
    response.end();
  }

  function createConversation(title) {
    const id = `${CONV_PREFIX}${String(nextId++).padStart(32, "0")}`;
    const row = { conversation_id: id, title, created_at: now(), updated_at: now() };
    conversations.unshift(row);
    messages.set(id, []);
    return row;
  }

  const server = createServer(async (request, response) => {
    const url = new URL(request.url, "http://mock");
    if (url.pathname === "/__revoke" && request.method === "POST") {
      sessions.clear();
      return json(response, 200, {});
    }
    if (url.pathname === "/v1/sessions" && request.method === "POST") {
      let body = "";
      for await (const chunk of request) body += chunk;
      const { username, password } = JSON.parse(body);
      if (username === "locked") {
        response.writeHead(429, { "Content-Type": "application/json", "Retry-After": "60" });
        return response.end(JSON.stringify({ error: { code: "SIGN_IN_THROTTLED", message: "m" } }));
      }
      if (username !== E2E_USERNAME || password !== E2E_PASSWORD) {
        return fail(response, 401, "INVALID_CREDENTIALS", "Wrong username or password.");
      }
      const token = `${E2E_TOKEN}${nextId++}`;
      sessions.add(token);
      const expiresAt = new Date(Date.now() + 12 * 3600 * 1000).toISOString();
      return json(response, 201, { session_token: token, principal_id: "user-1", expires_at: expiresAt });
    }
    const bearer = (request.headers.authorization ?? "").replace(/^Bearer /, "");
    if (url.pathname === "/v1/sessions/current" && request.method === "DELETE" && sessions.delete(bearer)) {
      response.writeHead(204);
      return response.end();
    }
    if (url.pathname === "/v1/sessions" && request.method === "DELETE" && sessions.has(bearer)) {
      sessions.clear();
      response.writeHead(204);
      return response.end();
    }
    if (url.pathname === "/__seed-long" && request.method === "POST") {
      const row = createConversation("Long conversation");
      for (let i = 1; i <= 150; i++) message(row.conversation_id, i % 2 ? "user" : "assistant", `Message ${i}`);
      return json(response, 201, row);
    }
    const limit = Number(url.searchParams.get("limit") ?? MAX_PAGE_SIZE);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    if (!(limit >= 1 && limit <= MAX_PAGE_SIZE) || !(offset >= 0)) {
      return json(response, 422, { error: { code: "VALIDATION_FAILED", message: "Request validation failed.", fields: { limit: "out of range" } } });
    }
    if (!sessions.has(bearer)) {
      return fail(response, 401, "UNAUTHENTICATED", "Missing or invalid API token.");
    }
    let body = "";
    for await (const chunk of request) body += chunk;
    const data = body ? JSON.parse(body) : {};

    if (url.pathname === "/v1/conversations" && request.method === "GET") {
      return json(response, 200, {
        data: conversations.slice(offset, offset + limit),
        meta: { total: conversations.length, limit, offset },
      });
    }
    if (url.pathname === "/v1/conversations" && request.method === "POST") {
      return json(response, 201, createConversation(data.title ?? "New conversation"));
    }
    const remember = /^\/v1\/conversations\/([^/]+)\/messages\/([^/]+)\/remember$/.exec(url.pathname);
    if (remember && request.method === "POST") {
      const found = messages.get(remember[1])?.find((row) => row.message_id === remember[2]);
      if (!found) return fail(response, 404, "MESSAGE_NOT_FOUND", "Message not found.");
      if (remembered.has(found.message_id)) return fail(response, 409, "ALREADY_REMEMBERED", "Already saved.");
      remembered.add(found.message_id);
      return json(response, 201, { record_id: `mem-${found.message_id}`, content: found.content });
    }
    const match = /^\/v1\/conversations\/([^/]+)\/messages$/.exec(url.pathname);
    if (match && messages.has(match[1])) {
      if (request.method === "GET") {
        const list = messages.get(match[1]);
        return json(response, 200, { data: list.slice(offset, offset + limit), meta: { total: list.length, limit, offset } });
      }
      if (request.method === "POST" && request.headers.accept === "text/event-stream") {
        return reply(response, match[1], data.content);
      }
    }
    return fail(response, 404, "NOT_FOUND", "Not found.");
  });

  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}
