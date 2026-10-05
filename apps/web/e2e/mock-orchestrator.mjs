// A stand-in orchestrator for the end-to-end test: the real API's paths, status codes,
// error envelope and SSE events, with canned replies chosen by the message text.

import { createServer } from "node:http";

export const E2E_TOKEN = "glp_e2e-synthetic-token_9f8e7d6c5b4a";

const CONV_PREFIX = "conv-";
const SSE_HEADERS = { "Content-Type": "text/event-stream", "Cache-Control": "no-store" };

export function startMockOrchestrator(port) {
  let revoked = false;
  let nextId = 1;
  const conversations = [];
  const messages = new Map();

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
      message_id: `msg-${nextId++}`,
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

  const server = createServer(async (request, response) => {
    const url = new URL(request.url, "http://mock");
    if (url.pathname === "/__revoke" && request.method === "POST") {
      revoked = true;
      return json(response, 200, {});
    }
    if (request.headers.authorization !== `Bearer ${E2E_TOKEN}` || revoked) {
      return fail(response, 401, "UNAUTHENTICATED", "Missing or invalid API token.");
    }
    let body = "";
    for await (const chunk of request) body += chunk;
    const data = body ? JSON.parse(body) : {};

    if (url.pathname === "/v1/conversations" && request.method === "GET") {
      return json(response, 200, { data: conversations, meta: { total: conversations.length, limit: 100, offset: 0 } });
    }
    if (url.pathname === "/v1/conversations" && request.method === "POST") {
      const id = `${CONV_PREFIX}${String(nextId++).padStart(32, "0")}`;
      const row = { conversation_id: id, title: data.title ?? "New conversation", created_at: now(), updated_at: now() };
      conversations.unshift(row);
      messages.set(id, []);
      return json(response, 201, row);
    }
    const match = /^\/v1\/conversations\/([^/]+)\/messages$/.exec(url.pathname);
    if (match && messages.has(match[1])) {
      if (request.method === "GET") {
        const list = messages.get(match[1]);
        return json(response, 200, { data: list, meta: { total: list.length, limit: 500, offset: 0 } });
      }
      if (request.method === "POST" && request.headers.accept === "text/event-stream") {
        return reply(response, match[1], data.content);
      }
    }
    return fail(response, 404, "NOT_FOUND", "Not found.");
  });

  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}
