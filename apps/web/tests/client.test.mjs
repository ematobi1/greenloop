import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { afterEach, test } from "node:test";
import { fileURLToPath } from "node:url";

import { ApiError, streamMessage } from "../src/lib/api.ts";
import { GENERIC_ERROR, isSignedOut, messageFor } from "../src/lib/errors.ts";
import { createSseParser } from "../src/lib/sse.ts";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const CONV = `conv-${"b".repeat(32)}`;

function parseAll(chunks) {
  const events = [];
  const parser = createSseParser((event) => events.push(event));
  for (const chunk of chunks) parser.push(chunk);
  parser.end();
  return events;
}

test("SSE events survive any chunk split, CRLF and a split \\r\\n", () => {
  const text = 'event: delta\r\ndata: {"text":"a"}\r\n\r\nevent: done\ndata: {"x":1}\n\n';
  const expected = [
    { event: "delta", data: '{"text":"a"}' },
    { event: "done", data: '{"x":1}' },
  ];
  for (let size = 1; size <= text.length; size++) {
    const chunks = [];
    for (let at = 0; at < text.length; at += size) chunks.push(text.slice(at, at + size));
    assert.deepEqual(parseAll(chunks), expected, `chunk size ${size}`);
  }
});

test("SSE comments are skipped, multi-line data is joined, and a missing event name is message", () => {
  assert.deepEqual(parseAll([": keep-alive\n\ndata: a\ndata: b\n\n"]), [{ event: "message", data: "a\nb" }]);
  assert.deepEqual(parseAll(["event: delta\ndata: tail"]), [{ event: "delta", data: "tail" }]);
  assert.deepEqual(parseAll(["event: delta\n\n"]), []);
});

test("each handled error code has its own wording; unknown codes get the generic one", () => {
  const busy = messageFor({ status: 409, code: "CONVERSATION_BUSY", message: "server text" });
  assert.match(busy, /still being written/);
  assert.match(messageFor({ status: 503, code: "AI_NOT_CONFIGURED", message: "" }), /No AI provider/);
  assert.match(messageFor({ status: 401, code: "WHATEVER", message: "" }), /Sign in again/);
  assert.equal(messageFor({ status: 500, code: "BOOM", message: "<b>server</b>" }), GENERIC_ERROR);
  assert.equal(isSignedOut({ status: 401, code: "x", message: "" }), true);
  assert.equal(isSignedOut({ status: 409, code: "x", message: "" }), false);
});

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function serve(response) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return response;
  };
  return calls;
}

function recorder() {
  const seen = [];
  return {
    seen,
    handlers: {
      onUserMessage: (message) => seen.push(["user", message.content]),
      onDelta: (text) => seen.push(["delta", text]),
      onDone: (message) => seen.push(["done", message.content]),
      onError: (failure, partial) => seen.push(["error", failure.code, partial?.content ?? null]),
    },
  };
}

const sse = (text) => new Response(text, { headers: { "content-type": "text/event-stream" } });

test("a streamed reply delivers message, deltas and done in order, same-origin only", async () => {
  const calls = serve(
    sse(
      'event: message\ndata: {"user_message":{"content":"hi"}}\n\n' +
        'event: delta\ndata: {"text":"Hel"}\n\nevent: delta\ndata: {"text":"lo"}\n\n' +
        'event: done\ndata: {"assistant_message":{"content":"Hello"}}\n\n',
    ),
  );
  const { seen, handlers } = recorder();
  await streamMessage(CONV, "hi", handlers);
  assert.deepEqual(seen, [["user", "hi"], ["delta", "Hel"], ["delta", "lo"], ["done", "Hello"]]);
  assert.equal(calls[0].url, `/api/conversations/${CONV}/messages`);
  assert.equal(calls[0].init.credentials, "same-origin");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
});

test("an error event passes the code and the kept partial reply", async () => {
  serve(
    sse(
      'event: delta\ndata: {"text":"Par"}\n\n' +
        'event: error\ndata: {"error":{"code":"AI_PROVIDER_ERROR","message":"m"},"partial_message":{"content":"Par"}}\n\n',
    ),
  );
  const { seen, handlers } = recorder();
  await streamMessage(CONV, "hi", handlers);
  assert.deepEqual(seen.at(-1), ["error", "AI_PROVIDER_ERROR", "Par"]);
});

test("a stream that ends without done or error reports a network failure", async () => {
  serve(sse('event: delta\ndata: {"text":"x"}\n\n'));
  const { seen, handlers } = recorder();
  await streamMessage(CONV, "hi", handlers);
  assert.deepEqual(seen.at(-1), ["error", "NETWORK", null]);
});

test("busy, not-configured and 401 before the stream throw ApiError with the code", async () => {
  for (const [status, code] of [
    [409, "CONVERSATION_BUSY"],
    [503, "AI_NOT_CONFIGURED"],
    [401, "SIGNED_OUT"],
  ]) {
    serve(Response.json({ error: { code, message: "m" } }, { status }));
    const { seen, handlers } = recorder();
    const error = await streamMessage(CONV, "hi", handlers).catch((caught) => caught);
    assert.ok(error instanceof ApiError, code);
    assert.deepEqual([error.failure.status, error.failure.code], [status, code]);
    assert.deepEqual(seen, []);
  }
});

function sourceFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? sourceFiles(path) : /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

test("no source renders raw HTML, uses browser storage, logs, or exposes env to the client", () => {
  for (const file of sourceFiles(SRC)) {
    const text = readFileSync(file, "utf8");
    const name = relative(SRC, file);
    for (const banned of [/dangerouslySetInnerHTML/, /\binnerHTML\b/, /localStorage|sessionStorage|indexedDB/, /console\./, /NEXT_PUBLIC_/]) {
      assert.ok(!banned.test(text), `${name} matches ${banned}`);
    }
  }
});

test("client components never import server modules", () => {
  for (const file of sourceFiles(SRC)) {
    const text = readFileSync(file, "utf8");
    if (!/^["']use client["']/.test(text)) continue;
    assert.ok(!/from ["'](@\/server|\.\.?\/.*server)/.test(text), `${relative(SRC, file)} imports server code`);
  }
});

test("security headers are set for every path", async () => {
  const { default: config } = await import("../next.config.ts");
  const rules = await config.headers();
  const all = rules.find((rule) => rule.source === "/:path*");
  const headers = Object.fromEntries(all.headers.map(({ key, value }) => [key, value]));
  assert.equal(headers["X-Frame-Options"], "DENY");
  assert.match(headers["Content-Security-Policy"], /frame-ancestors 'none'/);
  assert.equal(headers["X-Content-Type-Options"], "nosniff");
  assert.equal(headers["Referrer-Policy"], "no-referrer");
  assert.equal(config.poweredByHeader, false);
});
