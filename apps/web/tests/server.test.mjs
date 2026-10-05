import assert from "node:assert/strict";
import { test } from "node:test";

import { readServerConfig } from "../src/server/config.ts";
import { readJsonBody, rejectCrossSite, rejectNonJson } from "../src/server/guard.ts";
import { sanitizeErrorBody } from "../src/server/http.ts";
import { callOrchestrator, relayError, UpstreamFailure } from "../src/server/orchestrator.ts";
import {
  clearedSessionCookie,
  isPlausibleToken,
  readSessionToken,
  SESSION_COOKIE,
  sessionCookie,
} from "../src/server/session.ts";

const TOKEN = "glp_synthetic-test-token_0123456789";
const CONFIG = { orchestratorUrl: "http://orchestrator:8000", webOrigin: "http://127.0.0.1:3000" };

test("config needs both URLs and a bare WEB_ORIGIN", () => {
  assert.deepEqual(
    readServerConfig({ ORCHESTRATOR_URL: "http://orchestrator:8000/", WEB_ORIGIN: "http://127.0.0.1:3000" }),
    CONFIG,
  );
  assert.throws(() => readServerConfig({ WEB_ORIGIN: CONFIG.webOrigin }), /ORCHESTRATOR_URL is not set/);
  assert.throws(() => readServerConfig({ ORCHESTRATOR_URL: CONFIG.orchestratorUrl }), /WEB_ORIGIN is not set/);
  for (const bad of ["http://127.0.0.1:3000/", "http://127.0.0.1:3000/chat", "ftp://x"]) {
    assert.throws(() => readServerConfig({ ORCHESTRATOR_URL: CONFIG.orchestratorUrl, WEB_ORIGIN: bad }));
  }
  assert.throws(
    () => readServerConfig({ ORCHESTRATOR_URL: "file:///etc", WEB_ORIGIN: CONFIG.webOrigin }),
    /http or https/,
  );
});

test("session cookie has every protective attribute and a 12h Max-Age", () => {
  const cookie = sessionCookie(TOKEN);
  assert.ok(cookie.startsWith(`${SESSION_COOKIE}=${TOKEN};`));
  for (const attribute of ["Path=/", "Max-Age=43200", "HttpOnly", "Secure", "SameSite=Strict"]) {
    assert.ok(cookie.split("; ").includes(attribute), `missing ${attribute}`);
  }
  assert.ok(!/Domain=/i.test(cookie), "__Host- cookies must not set Domain");
  assert.ok(SESSION_COOKIE.startsWith("__Host-"));
});

test("clearing the session expires the same cookie with the same attributes", () => {
  const cookie = clearedSessionCookie();
  assert.ok(cookie.startsWith(`${SESSION_COOKIE}=;`));
  for (const attribute of ["Path=/", "Max-Age=0", "HttpOnly", "Secure", "SameSite=Strict"]) {
    assert.ok(cookie.split("; ").includes(attribute), `missing ${attribute}`);
  }
});

test("tokens that could break or inject into the cookie are refused", () => {
  for (const bad of ["", "has space", "semi;colon", "com,ma", 'quo"te', "back\\slash", "é", "x".repeat(513), 42, null]) {
    assert.equal(isPlausibleToken(bad), false, String(bad));
  }
  assert.throws(() => sessionCookie("a;b"), /malformed/);
  assert.equal(isPlausibleToken(TOKEN), true);
});

test("the session token is read only from its own cookie", () => {
  const request = (cookie) => new Request("http://x/", { headers: cookie ? { cookie } : {} });
  assert.equal(readSessionToken(request(`other=1; ${SESSION_COOKIE}=${TOKEN}`)), TOKEN);
  assert.equal(readSessionToken(request(`greenloop_session=${TOKEN}`)), null);
  assert.equal(readSessionToken(request(`${SESSION_COOKIE}=bad value`)), null);
  assert.equal(readSessionToken(request(null)), null);
});

test("cross-site requests are rejected against WEB_ORIGIN, not the Host header", async () => {
  const from = (origin, host = "127.0.0.1:3000") =>
    new Request("http://127.0.0.1:3000/api/session", {
      method: "POST",
      headers: { ...(origin ? { origin } : {}), host },
    });
  assert.equal(rejectCrossSite(from(CONFIG.webOrigin), CONFIG.webOrigin), null);
  for (const origin of [null, "http://evil.example", "http://localhost:3000", "null"]) {
    const rejected = rejectCrossSite(from(origin), CONFIG.webOrigin);
    assert.equal(rejected?.status, 403, String(origin));
    assert.equal((await rejected.json()).error.code, "CROSS_SITE_REQUEST");
  }
  // A forged Host that matches the forged Origin still fails.
  assert.equal(rejectCrossSite(from("http://evil.example", "evil.example"), CONFIG.webOrigin)?.status, 403);
});

test("state-changing bodies must be JSON", async () => {
  const typed = (type) => new Request("http://x/", { method: "POST", headers: type ? { "content-type": type } : {} });
  assert.equal(rejectNonJson(typed("application/json")), null);
  assert.equal(rejectNonJson(typed("application/json; charset=utf-8")), null);
  for (const type of [null, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"]) {
    assert.equal(rejectNonJson(typed(type))?.status, 415, String(type));
  }
  assert.equal(await readJsonBody(new Request("http://x/", { method: "POST", body: "{bad" }), 1024), undefined);
});

test("error bodies keep only code, message and string fields", () => {
  assert.deepEqual(
    sanitizeErrorBody({
      error: { code: "VALIDATION_FAILED", message: "m", fields: { a: "x", b: 1 }, trace: "secret" },
      extra: "dropped",
    }),
    { error: { code: "VALIDATION_FAILED", message: "m", fields: { a: "x" } } },
  );
  for (const bad of [null, "x", {}, { error: "x" }, { error: { code: 1, message: "m" } }]) {
    assert.equal(sanitizeErrorBody(bad), null);
  }
});

function recordingFetch(response) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    if (response instanceof Error) throw response;
    return typeof response === "function" ? response(init) : response;
  };
  return { calls, fetchImpl };
}

test("the outbound call carries the token only in Authorization", async () => {
  const { calls, fetchImpl } = recordingFetch(new Response("{}"));
  await callOrchestrator(
    { config: CONFIG, fetch: fetchImpl, timeoutMs: 1000 },
    { method: "POST", path: "/v1/conversations", token: TOKEN, body: { title: "t" }, stream: true },
  );
  const [{ url, init }] = calls;
  assert.equal(url, "http://orchestrator:8000/v1/conversations");
  assert.equal(init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(init.headers.Accept, "text/event-stream");
  assert.equal(init.headers["Content-Type"], "application/json");
  assert.equal(init.redirect, "error");
  assert.ok(!url.includes(TOKEN) && !init.body.includes(TOKEN));
});

test("an unreachable orchestrator is a 502 and a slow one a 504", async () => {
  const upstream = (fetchImpl, timeoutMs = 1000) => ({ config: CONFIG, fetch: fetchImpl, timeoutMs });
  const call = { method: "GET", path: "/v1/conversations", token: TOKEN };

  const down = recordingFetch(new TypeError("fetch failed"));
  const failure = await callOrchestrator(upstream(down.fetchImpl), call).catch((error) => error);
  assert.ok(failure instanceof UpstreamFailure);
  assert.equal(failure.response.status, 502);

  const hang = (_url, init) =>
    new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(new Error("aborted"))));
  const slow = await callOrchestrator(upstream(hang, 20), call).catch((error) => error);
  assert.equal(slow.response.status, 504);
  assert.equal((await slow.response.json()).error.code, "ORCHESTRATOR_TIMEOUT");
});

test("an aborted client request aborts the outbound call", async () => {
  const client = new AbortController();
  let outbound;
  const fetchImpl = async (_url, init) => {
    outbound = init.signal;
    return new Response("{}");
  };
  await callOrchestrator(
    { config: CONFIG, fetch: fetchImpl, timeoutMs: 1000 },
    { method: "GET", path: "/v1/conversations", token: TOKEN, signal: client.signal },
  );
  assert.equal(outbound.aborted, false);
  client.abort();
  assert.equal(outbound.aborted, true);
});

test("relayed errors are sanitized, and a 401 clears the session cookie", async () => {
  const unauthorized = await relayError(
    Response.json({ error: { code: "UNAUTHENTICATED", message: "m", stack: "x" } }, { status: 401 }),
  );
  assert.equal(unauthorized.status, 401);
  assert.deepEqual(await unauthorized.json(), { error: { code: "UNAUTHENTICATED", message: "m" } });
  assert.ok(unauthorized.headers.get("set-cookie").includes("Max-Age=0"));

  const busy = await relayError(Response.json({ error: { code: "CONVERSATION_BUSY", message: "m" } }, { status: 409 }));
  assert.equal(busy.status, 409);
  assert.equal(busy.headers.get("set-cookie"), null);

  const garbage = await relayError(new Response("<html>oops</html>", { status: 500 }));
  assert.equal(garbage.status, 502);
  assert.equal((await garbage.json()).error.code, "ORCHESTRATOR_ERROR");
});

test("a body whose upload fails reads as no body instead of throwing", async () => {
  const broken = new Request("http://x/", {
    method: "POST",
    body: new ReadableStream({
      pull(controller) {
        controller.error(new Error("client went away"));
      },
    }),
    duplex: "half",
  });
  assert.equal(await readJsonBody(broken, 1024), undefined);
});
