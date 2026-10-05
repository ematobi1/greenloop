import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createConversation,
  listConversations,
  listMessages,
  sendMessage,
  sessionStatus,
  signIn,
  signOut,
} from "../src/server/handlers.ts";
import { SESSION_COOKIE } from "../src/server/session.ts";

const TOKEN = "glp_synthetic-test-token_0123456789";
const ORIGIN = "http://127.0.0.1:3000";
const CONV = `conv-${"a".repeat(32)}`;

function upstream(reply) {
  const calls = [];
  return {
    calls,
    deps: {
      config: { orchestratorUrl: "http://orchestrator:8000", webOrigin: ORIGIN },
      timeoutMs: 1000,
      fetch: async (url, init) => {
        calls.push({ url, init });
        return typeof reply === "function" ? reply(url, init) : reply.clone();
      },
    },
  };
}

function request(path, { method = "GET", body, signedIn = true, origin = ORIGIN, type = "application/json", signal } = {}) {
  const headers = {};
  if (signedIn) headers.cookie = `${SESSION_COOKIE}=${TOKEN}`;
  if (origin) headers.origin = origin;
  if (body !== undefined && type) headers["content-type"] = type;
  return new Request(`${ORIGIN}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
    signal,
  });
}

const sse = (text) => new Response(text, { headers: { "content-type": "text/event-stream" } });
const apiError = (status, code) => Response.json({ error: { code, message: `${code} message` } }, { status });

async function assertNoToken(response) {
  const text = await response.clone().text();
  assert.ok(!text.includes(TOKEN), "token leaked into a response body");
  for (const [name, value] of response.headers) {
    if (name === "set-cookie" && value.startsWith(`${SESSION_COOKIE}=${TOKEN};`)) continue;
    assert.ok(!value.includes(TOKEN), `token leaked into header ${name}`);
  }
}

test("session status reports only whether a session cookie exists", async () => {
  assert.deepEqual(await sessionStatus(request("/api/session")).json(), { signed_in: true });
  assert.deepEqual(await sessionStatus(request("/api/session", { signedIn: false })).json(), { signed_in: false });
});

test("sign-in checks the token upstream, then sets the cookie and returns no body", async () => {
  const { calls, deps } = upstream(Response.json({ data: [], meta: { total: 0, limit: 1, offset: 0 } }));
  const response = await signIn(request("/api/session", { method: "POST", body: { token: TOKEN }, signedIn: false }), deps);
  assert.equal(response.status, 204);
  assert.equal(await response.text(), "");
  assert.ok(response.headers.get("set-cookie").startsWith(`${SESSION_COOKIE}=${TOKEN};`));
  assert.equal(calls[0].url, "http://orchestrator:8000/v1/conversations?limit=1");
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
});

test("sign-in with a rejected token sets no cookie", async () => {
  const { deps } = upstream(apiError(401, "UNAUTHENTICATED"));
  const response = await signIn(request("/api/session", { method: "POST", body: { token: TOKEN }, signedIn: false }), deps);
  assert.equal(response.status, 401);
  assert.equal((await response.json()).error.code, "INVALID_TOKEN");
  assert.equal(response.headers.get("set-cookie"), null);
});

test("sign-in refuses malformed tokens without calling upstream", async () => {
  for (const token of [undefined, "", "two words", "a;b", 7]) {
    const { calls, deps } = upstream(new Response("{}"));
    const response = await signIn(request("/api/session", { method: "POST", body: { token }, signedIn: false }), deps);
    assert.equal(response.status, 422, String(token));
    assert.equal(calls.length, 0);
  }
});

test("sign-in and sign-out refuse cross-site requests", async () => {
  const { calls, deps } = upstream(new Response("{}"));
  for (const origin of [null, "http://evil.example"]) {
    const response = await signIn(request("/api/session", { method: "POST", body: { token: TOKEN }, origin }), deps);
    assert.equal(response.status, 403);
    assert.equal((await signOut(request("/api/session", { method: "DELETE", origin }), deps)).status, 403);
  }
  const form = await signIn(
    request("/api/session", { method: "POST", body: `token=${TOKEN}`, type: "application/x-www-form-urlencoded" }),
    deps,
  );
  assert.equal(form.status, 415);
  assert.equal(calls.length, 0);
});

test("sign-out clears the cookie", async () => {
  const { deps } = upstream(new Response("{}"));
  const response = await signOut(request("/api/session", { method: "DELETE" }), deps);
  assert.equal(response.status, 204);
  assert.ok(response.headers.get("set-cookie").includes("Max-Age=0"));
});

test("every proxied call without a session is 401 and never reaches upstream", async () => {
  const { calls, deps } = upstream(new Response("{}"));
  const out = { signedIn: false };
  const responses = [
    await listConversations(request("/api/conversations", out), deps),
    await createConversation(request("/api/conversations", { ...out, method: "POST", body: {} }), deps),
    await listMessages(request(`/api/conversations/${CONV}/messages`, out), CONV, deps),
    await sendMessage(request(`/api/conversations/${CONV}/messages`, { ...out, method: "POST", body: { content: "hi" } }), CONV, deps),
  ];
  for (const response of responses) {
    assert.equal(response.status, 401);
    assert.equal((await response.json()).error.code, "SIGNED_OUT");
  }
  assert.equal(calls.length, 0);
});

test("conversations are listed and created through the orchestrator", async () => {
  const page = { data: [{ conversation_id: CONV, title: "t" }], meta: { total: 1, limit: 100, offset: 0 } };
  const listed = upstream(Response.json(page));
  const list = await listConversations(request("/api/conversations"), listed.deps);
  assert.deepEqual(await list.json(), page);
  assert.equal(list.headers.get("cache-control"), "no-store");

  const created = upstream(Response.json(page.data[0], { status: 201 }));
  const create = await createConversation(request("/api/conversations", { method: "POST", body: { title: "t" } }), created.deps);
  assert.equal(create.status, 201);
  assert.deepEqual(JSON.parse(created.calls[0].init.body), { title: "t" });
  await assertNoToken(create);

  for (const title of ["", "   ", 5, "x".repeat(201)]) {
    const response = await createConversation(request("/api/conversations", { method: "POST", body: { title } }), created.deps);
    assert.equal(response.status, 422, String(title));
  }
});

test("conversation ids outside the orchestrator's format never reach upstream", async () => {
  const { calls, deps } = upstream(new Response("{}"));
  for (const id of ["../admin", "conv-xyz", `conv-${"A".repeat(32)}`, `${CONV}?x=1`, `${CONV}/../..`]) {
    assert.equal((await listMessages(request("/api/conversations/x/messages"), id, deps)).status, 404, id);
    const send = await sendMessage(request("/api/conversations/x/messages", { method: "POST", body: { content: "hi" } }), id, deps);
    assert.equal(send.status, 404, id);
  }
  assert.equal(calls.length, 0);
});

test("a sent message streams the orchestrator's SSE body through", async () => {
  const body = 'event: message\ndata: {"user_message":{}}\n\nevent: delta\ndata: {"text":"Hi"}\n\n';
  const { calls, deps } = upstream(sse(body));
  const response = await sendMessage(
    request(`/api/conversations/${CONV}/messages`, { method: "POST", body: { content: "hello" } }),
    CONV,
    deps,
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/event-stream");
  assert.equal(response.headers.get("x-accel-buffering"), "no");
  assert.equal(await response.text(), body);
  assert.equal(calls[0].init.headers.Accept, "text/event-stream");
  assert.deepEqual(JSON.parse(calls[0].init.body), { content: "hello" });
});

test("a send is refused when blank, cross-site or not JSON", async () => {
  const { calls, deps } = upstream(sse(""));
  const path = `/api/conversations/${CONV}/messages`;
  for (const content of ["", "  \n", 3, undefined]) {
    assert.equal((await sendMessage(request(path, { method: "POST", body: { content } }), CONV, deps)).status, 422);
  }
  assert.equal(
    (await sendMessage(request(path, { method: "POST", body: { content: "x" }, origin: "http://evil.example" }), CONV, deps)).status,
    403,
  );
  assert.equal(
    (await sendMessage(request(path, { method: "POST", body: "content=x", type: "text/plain" }), CONV, deps)).status,
    415,
  );
  assert.equal(calls.length, 0);
});

test("busy, not-configured and expired-token errors come back as clean JSON", async () => {
  const path = `/api/conversations/${CONV}/messages`;
  for (const [status, code] of [
    [409, "CONVERSATION_BUSY"],
    [503, "AI_NOT_CONFIGURED"],
    [401, "UNAUTHENTICATED"],
  ]) {
    const { deps } = upstream(apiError(status, code));
    const response = await sendMessage(request(path, { method: "POST", body: { content: "x" } }), CONV, deps);
    assert.equal(response.status, status);
    assert.equal((await response.clone().json()).error.code, code);
    assert.equal(response.headers.has("set-cookie"), status === 401, code);
    await assertNoToken(response);
  }
});

test("a non-SSE success from upstream is not passed through", async () => {
  const { deps } = upstream(Response.json({ user_message: {}, assistant_message: {} }));
  const response = await sendMessage(
    request(`/api/conversations/${CONV}/messages`, { method: "POST", body: { content: "x" } }),
    CONV,
    deps,
  );
  assert.equal(response.status, 502);
});

test("an aborted browser request aborts the streamed upstream call", async () => {
  const browser = new AbortController();
  let outbound;
  const { deps } = upstream((_url, init) => {
    outbound = init.signal;
    return sse("event: delta\ndata: {}\n\n");
  });
  await sendMessage(
    request(`/api/conversations/${CONV}/messages`, { method: "POST", body: { content: "x" }, signal: browser.signal }),
    CONV,
    deps,
  );
  browser.abort();
  assert.equal(outbound.aborted, true);
});
