import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createConversation,
  currentSession,
  listConversations,
  listMessages,
  PAGE_SIZE,
  PLAN_TIMEOUT_MS,
  deleteMemory,
  discardPlan,
  draftPlan,
  listMemory,
  memoryHistory,
  rememberMessage,
  reviseMemory,
  sendMessage,
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

const CREDENTIALS = { username: "alice", password: "correct horse battery staple" };
const session = (seconds = 3600) =>
  Response.json(
    { session_token: TOKEN, principal_id: "user-1", expires_at: new Date(Date.now() + seconds * 1000).toISOString() },
    { status: 201 },
  );

test("sign-in trades username and password for a session cookie and returns no body", async () => {
  const { calls, deps } = upstream(session());
  const response = await signIn(request("/api/session", { method: "POST", body: CREDENTIALS, signedIn: false }), deps);
  assert.equal(response.status, 204);
  assert.equal(await response.text(), "");
  const cookie = response.headers.get("set-cookie");
  assert.ok(cookie.startsWith(`${SESSION_COOKIE}=${TOKEN};`));
  const maxAge = Number(/Max-Age=(\d+)/.exec(cookie)[1]);
  assert.ok(maxAge > 3500 && maxAge <= 3600, `Max-Age ${maxAge} follows the session's expiry`);
  assert.equal(calls[0].url, "http://orchestrator:8000/v1/sessions");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), CREDENTIALS);
  assert.equal(calls[0].init.headers.Authorization, undefined);
});

test("the cookie never outlives 12 hours whatever the server says", async () => {
  const { deps } = upstream(session(7 * 24 * 3600));
  const response = await signIn(request("/api/session", { method: "POST", body: CREDENTIALS, signedIn: false }), deps);
  assert.match(response.headers.get("set-cookie"), /Max-Age=43200;/);
});

test("wrong credentials and lockouts are relayed and set no cookie", async () => {
  const wrong = await signIn(
    request("/api/session", { method: "POST", body: CREDENTIALS, signedIn: false }),
    upstream(apiError(401, "INVALID_CREDENTIALS")).deps,
  );
  assert.equal(wrong.status, 401);
  assert.equal((await wrong.json()).error.code, "INVALID_CREDENTIALS");
  assert.ok(!wrong.headers.get("set-cookie")?.includes(TOKEN));

  const throttled = new Response(JSON.stringify({ error: { code: "SIGN_IN_THROTTLED", message: "m" } }), {
    status: 429,
    headers: { "retry-after": "120", "content-type": "application/json" },
  });
  const locked = await signIn(
    request("/api/session", { method: "POST", body: CREDENTIALS, signedIn: false }),
    upstream(throttled).deps,
  );
  assert.equal(locked.status, 429);
  assert.equal(locked.headers.get("retry-after"), "120");
  assert.equal(locked.headers.get("set-cookie"), null);
});

test("an unexpected sign-in reply sets no cookie", async () => {
  for (const reply of [Response.json({ session_token: "bad token", expires_at: "2030-01-01T00:00:00Z" }), Response.json({})]) {
    const response = await signIn(request("/api/session", { method: "POST", body: CREDENTIALS, signedIn: false }), upstream(reply).deps);
    assert.equal(response.status, 502);
    assert.equal(response.headers.get("set-cookie"), null);
  }
});

test("sign-in refuses missing or oversized fields without calling upstream", async () => {
  for (const body of [{}, { username: "alice" }, { password: "x" }, { username: " ", password: "x" }, { username: "x".repeat(65), password: "x" }, { username: "a", password: "x".repeat(257) }, { token: TOKEN }]) {
    const { calls, deps } = upstream(new Response("{}"));
    const response = await signIn(request("/api/session", { method: "POST", body, signedIn: false }), deps);
    assert.equal(response.status, 422, JSON.stringify(body));
    assert.equal(calls.length, 0);
  }
});

test("sign-in and sign-out refuse cross-site requests", async () => {
  const { calls, deps } = upstream(new Response("{}"));
  for (const origin of [null, "http://evil.example"]) {
    const response = await signIn(request("/api/session", { method: "POST", body: CREDENTIALS, origin }), deps);
    assert.equal(response.status, 403);
    assert.equal((await signOut(request("/api/session", { method: "DELETE", origin }), deps)).status, 403);
  }
  const form = await signIn(
    request("/api/session", { method: "POST", body: "username=a&password=b", type: "application/x-www-form-urlencoded" }),
    deps,
  );
  assert.equal(form.status, 415);
  assert.equal(calls.length, 0);
});

test("sign-out revokes this session upstream and clears the cookie", async () => {
  const { calls, deps } = upstream(new Response(null, { status: 204 }));
  const response = await signOut(request("/api/session", { method: "DELETE" }), deps);
  assert.equal(response.status, 204);
  assert.ok(response.headers.get("set-cookie").includes("Max-Age=0"));
  assert.equal(calls[0].url, "http://orchestrator:8000/v1/sessions/current");
  assert.equal(calls[0].init.method, "DELETE");
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
});

test("sign-out everywhere revokes every session upstream", async () => {
  const { calls, deps } = upstream(new Response(null, { status: 204 }));
  const response = await signOut(request("/api/session?scope=all", { method: "DELETE" }), deps);
  assert.equal(response.status, 204);
  assert.equal(calls[0].url, "http://orchestrator:8000/v1/sessions");
});

test("the cookie is cleared even when the orchestrator can't be reached", async () => {
  const deps = {
    config: { orchestratorUrl: "http://orchestrator:8000", webOrigin: ORIGIN },
    timeoutMs: 1000,
    fetch: async () => {
      throw new TypeError("fetch failed");
    },
  };
  const single = await signOut(request("/api/session", { method: "DELETE" }), deps);
  assert.equal(single.status, 204);
  assert.ok(single.headers.get("set-cookie").includes("Max-Age=0"));
  const everywhere = await signOut(request("/api/session?scope=all", { method: "DELETE" }), deps);
  assert.equal(everywhere.status, 502, "the user must learn that other devices were not signed out");
  assert.ok(everywhere.headers.get("set-cookie").includes("Max-Age=0"));
});

test("signing out without a session clears the cookie without calling upstream", async () => {
  const { calls, deps } = upstream(new Response(null, { status: 204 }));
  const response = await signOut(request("/api/session", { method: "DELETE", signedIn: false }), deps);
  assert.equal(response.status, 204);
  assert.equal(calls.length, 0);
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

test("pages never ask the orchestrator for more than its 100-row limit", async () => {
  assert.equal(PAGE_SIZE, 100);
  const listed = upstream(Response.json({ data: [], meta: { total: 0, limit: 100, offset: 0 } }));
  await listConversations(request("/api/conversations"), listed.deps);
  assert.equal(listed.calls[0].url, "http://orchestrator:8000/v1/conversations?limit=100");

  const messages = upstream(Response.json({ data: [], meta: { total: 0, limit: 100, offset: 0 } }));
  await listMessages(request(`/api/conversations/${CONV}/messages`), CONV, messages.deps);
  await listMessages(request(`/api/conversations/${CONV}/messages?offset=50`), CONV, messages.deps);
  assert.deepEqual(
    messages.calls.map((call) => call.url),
    [
      `http://orchestrator:8000/v1/conversations/${CONV}/messages?limit=100&offset=0`,
      `http://orchestrator:8000/v1/conversations/${CONV}/messages?limit=100&offset=50`,
    ],
  );
});

test("a message offset must be a plain whole number", async () => {
  const { calls, deps } = upstream(new Response("{}"));
  for (const offset of ["-1", "1.5", "abc", "1e3", "99999999999", "0x10", "5&limit=500"]) {
    const response = await listMessages(
      request(`/api/conversations/${CONV}/messages?offset=${encodeURIComponent(offset)}`),
      CONV,
      deps,
    );
    assert.equal(response.status, 422, offset);
  }
  assert.equal(calls.length, 0);
});

test("oversized bodies are refused before they are buffered", async () => {
  const { calls, deps } = upstream(new Response("{}"));
  const big = JSON.stringify({ token: "x".repeat(9000) });
  const declared = await signIn(request("/api/session", { method: "POST", body: big, signedIn: false }), deps);
  assert.equal(declared.status, 413);

  // No Content-Length: the streamed size counts.
  const streamed = new Request(`${ORIGIN}/api/session`, {
    method: "POST",
    headers: { origin: ORIGIN, "content-type": "application/json" },
    body: new ReadableStream({
      start(controller) {
        for (let i = 0; i < 20; i++) controller.enqueue(new TextEncoder().encode("x".repeat(1024)));
        controller.close();
      },
    }),
    duplex: "half",
  });
  assert.equal((await signIn(streamed, deps)).status, 413);

  const hugeMessage = JSON.stringify({ content: "x".repeat(1024 * 1024 + 1) });
  const send = await sendMessage(
    request(`/api/conversations/${CONV}/messages`, { method: "POST", body: hugeMessage }),
    CONV,
    deps,
  );
  assert.equal(send.status, 413);
  assert.equal(calls.length, 0);
});

test("the SSE relay forbids caching and transformation", async () => {
  const { deps } = upstream(sse("event: delta\ndata: {}\n\n"));
  const response = await sendMessage(
    request(`/api/conversations/${CONV}/messages`, { method: "POST", body: { content: "x" } }),
    CONV,
    deps,
  );
  assert.equal(response.headers.get("cache-control"), "no-store, no-transform");
});

test("remembering a message forwards only the ids, never a body from the browser", async () => {
  const MSG = `msg-${"c".repeat(32)}`;
  const { calls, deps } = upstream(Response.json({ record_id: "mem-1" }, { status: 201 }));
  const response = await rememberMessage(
    request(`/api/conversations/${CONV}/messages/${MSG}/remember`, { method: "POST", body: { content: "x" } }),
    CONV,
    MSG,
    deps,
  );
  assert.equal(response.status, 201);
  assert.equal(calls[0].url, `http://orchestrator:8000/v1/conversations/${CONV}/messages/${MSG}/remember`);
  assert.deepEqual(JSON.parse(calls[0].init.body), {});
});

test("remember refuses bad ids, cross-site requests and missing sessions without calling upstream", async () => {
  const MSG = `msg-${"c".repeat(32)}`;
  const { calls, deps } = upstream(new Response("{}"));
  const path = "/api/conversations/x/messages/y/remember";
  for (const [conversationId, messageId] of [[CONV, "msg-xyz"], ["conv-1", MSG], [CONV, "../.."]]) {
    const response = await rememberMessage(request(path, { method: "POST", body: {} }), conversationId, messageId, deps);
    assert.equal(response.status, 404);
  }
  assert.equal(
    (await rememberMessage(request(path, { method: "POST", body: {}, origin: "http://evil.example" }), CONV, MSG, deps)).status,
    403,
  );
  assert.equal(
    (await rememberMessage(request(path, { method: "POST", body: {}, signedIn: false }), CONV, MSG, deps)).status,
    401,
  );
  assert.equal(calls.length, 0);
});

const MEM = `mem-${"d".repeat(32)}`;
const pageOf = (data) => Response.json({ data, meta: { total: data.length, limit: 100, offset: 0 } });

test("memory search forwards only q, offset and the page limit", async () => {
  const { calls, deps } = upstream(pageOf([]));
  await listMemory(request("/api/memory?q=%20green%20tea%20&offset=100&scope=shared&limit=999"), deps);
  const url = new URL(calls[0].url);
  assert.equal(url.pathname, "/v1/memory-records");
  assert.deepEqual(Object.fromEntries(url.searchParams), { limit: "100", offset: "100", q: "green tea" });
  for (const bad of ["?offset=-1", "?offset=x", `?q=${"x".repeat(201)}`]) {
    assert.equal((await listMemory(request(`/api/memory${bad}`), deps)).status, 422, bad);
  }
  assert.equal(calls.length, 1);
});

test("memory history and delete need a real record id", async () => {
  const { calls, deps } = upstream(pageOf([]));
  assert.equal((await memoryHistory(request("/api/memory/x/history"), MEM, deps)).status, 200);
  assert.equal(calls[0].url, `http://orchestrator:8000/v1/memory-records/${MEM}/history`);
  for (const id of ["mem-1", "../x", `${MEM}/history`]) {
    assert.equal((await memoryHistory(request("/api/memory/x/history"), id, deps)).status, 404, id);
    assert.equal((await deleteMemory(request("/api/memory/x", { method: "DELETE" }), id, deps)).status, 404, id);
  }
  assert.equal(calls.length, 1);
});

test("deleting memory is a guarded DELETE upstream", async () => {
  const { calls, deps } = upstream(new Response(null, { status: 204 }));
  assert.equal((await deleteMemory(request("/api/memory/x", { method: "DELETE" }), MEM, deps)).status, 204);
  assert.deepEqual([calls[0].init.method, calls[0].url], ["DELETE", `http://orchestrator:8000/v1/memory-records/${MEM}`]);
  const forged = await deleteMemory(request("/api/memory/x", { method: "DELETE", origin: "http://evil.example" }), MEM, deps);
  assert.equal(forged.status, 403);
  assert.equal(calls.length, 1);
});

test("revisions forward operation and content, and never a confidence", async () => {
  const { calls, deps } = upstream(Response.json({ record_id: MEM }, { status: 201 }));
  const path = "/api/memory/x/revisions";
  const ok = await reviseMemory(
    request(path, { method: "POST", body: { operation: "correct", content: "Tea, not coffee.", confidence: "verified" } }),
    MEM,
    deps,
  );
  assert.equal(ok.status, 201);
  assert.deepEqual(JSON.parse(calls[0].init.body), { operation: "correct", content: "Tea, not coffee." });
  const replace = await reviseMemory(
    request(path, { method: "POST", body: { operation: "supersede", content: "x", category: "decision" } }),
    MEM,
    deps,
  );
  assert.equal(replace.status, 201);
  assert.deepEqual(JSON.parse(calls[1].init.body), { operation: "supersede", content: "x", category: "decision" });
  for (const body of [
    { operation: "delete", content: "x" },
    { operation: "correct", content: " " },
    { operation: "correct", content: "x".repeat(20001) },
    { operation: "correct", content: "x", category: "decision" },
    { operation: "supersede", content: "x", category: "made_up" },
  ]) {
    assert.equal((await reviseMemory(request(path, { method: "POST", body }), MEM, deps)).status, 422, JSON.stringify(body));
  }
  assert.equal(calls.length, 2);
});

test("drafting a plan forwards only goal and conversation id, with the long timeout", async () => {
  const { calls, deps } = upstream(Response.json({ plan_id: "plan-1" }, { status: 201 }));
  const response = await draftPlan(
    request("/api/plans", { method: "POST", body: { goal: "Move my blog", conversation_id: CONV, steps: [], principal_id: "x" } }),
    deps,
  );
  assert.equal(response.status, 201);
  assert.equal(calls[0].url, "http://orchestrator:8000/v1/plans");
  assert.deepEqual(JSON.parse(calls[0].init.body), { goal: "Move my blog", conversation_id: CONV });
  for (const body of [{}, { goal: " " }, { goal: "x".repeat(2001) }, { goal: "x", conversation_id: "../x" }]) {
    const rejected = await draftPlan(request("/api/plans", { method: "POST", body }), deps);
    assert.ok([404, 422].includes(rejected.status), JSON.stringify(body));
  }
  assert.equal(calls.length, 1);
  assert.equal(PLAN_TIMEOUT_MS, 150_000);
});

test("plan drafting outlives the default timeout but not the plan timeout", async () => {
  let timeout;
  const deps = {
    config: { orchestratorUrl: "http://orchestrator:8000", webOrigin: ORIGIN },
    timeoutMs: 20,
    fetch: (_url, init) =>
      new Promise((resolve) => {
        const timer = setTimeout(() => resolve(Response.json({ plan_id: "p" }, { status: 201 })), 60);
        init.signal.addEventListener("abort", () => {
          clearTimeout(timer);
          timeout = init.signal.reason;
        });
      }),
  };
  const response = await draftPlan(request("/api/plans", { method: "POST", body: { goal: "x" } }), deps);
  assert.equal(response.status, 201, "a slow draft is not cut off by the 20 ms default");
  assert.equal(timeout, undefined);
});

test("discarding a plan is a guarded DELETE on a real plan id", async () => {
  const PLAN = `plan-${"e".repeat(32)}`;
  const { calls, deps } = upstream(new Response(null, { status: 204 }));
  assert.equal((await discardPlan(request("/api/plans/x", { method: "DELETE" }), PLAN, deps)).status, 204);
  assert.deepEqual([calls[0].init.method, calls[0].url], ["DELETE", `http://orchestrator:8000/v1/plans/${PLAN}`]);
  assert.equal((await discardPlan(request("/api/plans/x", { method: "DELETE" }), "plan-1", deps)).status, 404);
  assert.equal((await discardPlan(request("/api/plans/x", { method: "DELETE", origin: "http://evil.example" }), PLAN, deps)).status, 403);
  assert.equal(calls.length, 1);
});

test("execution memories written by dispatches can be managed too", async () => {
  const EXEC = `mem-exec-${"f".repeat(32)}`;
  const { calls, deps } = upstream(new Response(null, { status: 204 }));
  assert.equal((await deleteMemory(request("/api/memory/x", { method: "DELETE" }), EXEC, deps)).status, 204);
  assert.equal(calls[0].url, `http://orchestrator:8000/v1/memory-records/${EXEC}`);
  assert.equal((await deleteMemory(request("/api/memory/x", { method: "DELETE" }), "mem-other-1", deps)).status, 404);
});

test("a session reply that has already expired here sets no cookie", async () => {
  const stale = Response.json(
    { session_token: TOKEN, principal_id: "user-1", expires_at: new Date(Date.now() - 60_000).toISOString() },
    { status: 201 },
  );
  const response = await signIn(
    request("/api/session", { method: "POST", body: { username: "alice", password: "pw" }, signedIn: false }),
    upstream(stale).deps,
  );
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("set-cookie"), null);
});

test("the current session passes on only username, display name and expiry", async () => {
  const { calls, deps } = upstream(
    Response.json({ principal_id: "user-1", username: "terry", display_name: "Terry", expires_at: "2030-01-01T00:00:00Z", extra: "x" }),
  );
  const response = await currentSession(request("/api/session"), deps);
  assert.deepEqual(await response.json(), { username: "terry", display_name: "Terry", expires_at: "2030-01-01T00:00:00Z" });
  assert.equal(calls[0].url, "http://orchestrator:8000/v1/sessions/current");
  const signedOutResponse = await currentSession(request("/api/session", { signedIn: false }), deps);
  assert.equal(signedOutResponse.status, 401);
  const expired = await currentSession(request("/api/session"), upstream(apiError(401, "UNAUTHENTICATED")).deps);
  assert.equal(expired.status, 401);
  assert.ok(expired.headers.get("set-cookie").includes("Max-Age=0"));
});
