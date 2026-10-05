// Builds handler dependencies from the server environment at request time.

import { readServerConfig } from "./config.ts";
import type { Deps } from "./handlers.ts";
import { DEFAULT_TIMEOUT_MS } from "./orchestrator.ts";

export function serverDeps(): Deps {
  return { config: readServerConfig(process.env), fetch: globalThis.fetch, timeoutMs: DEFAULT_TIMEOUT_MS };
}
