// Builds handler dependencies from the server environment at request time. The
// server-only import makes any client bundle that reaches this module fail to build;
// the pure modules it wires up stay importable from node:test.

import "server-only";

import { readServerConfig } from "./config.ts";
import type { Deps } from "./handlers.ts";
import { DEFAULT_TIMEOUT_MS } from "./orchestrator.ts";

export function serverDeps(): Deps {
  return { config: readServerConfig(process.env), fetch: globalThis.fetch, timeoutMs: DEFAULT_TIMEOUT_MS };
}
