// Starts the mock orchestrator and `next start` for the e2e run, with the Next server's
// stdout and stderr written to test-results/next-server.log so a test can check that
// nothing sensitive is ever logged.

import { spawn } from "node:child_process";
import { createWriteStream, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { startMockOrchestrator } from "./mock-orchestrator.mjs";
import { MOCK_PORT, SERVER_LOG, WEB_ORIGIN, WEB_PORT } from "./ports.mjs";

async function waitForServer(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fetch(url);
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw new Error(`${url} did not start within ${timeoutMs} ms`);
}

export default async function globalSetup() {
  // A server already on these ports would answer instead of ours.
  for (const url of [WEB_ORIGIN, `http://127.0.0.1:${MOCK_PORT}`]) {
    const taken = await fetch(url).then(
      () => true,
      () => false,
    );
    if (taken) throw new Error(`${url} is already in use; stop that server first.`);
  }
  const mock = await startMockOrchestrator(MOCK_PORT);
  mkdirSync(new URL(".", SERVER_LOG), { recursive: true });
  const log = createWriteStream(SERVER_LOG);
  const nextBin = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));
  const server = spawn(process.execPath, [nextBin, "start", "-p", String(WEB_PORT), "-H", "127.0.0.1"], {
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    env: {
      PATH: process.env.PATH,
      SYSTEMROOT: process.env.SYSTEMROOT,
      NODE_ENV: "production",
      ORCHESTRATOR_URL: `http://127.0.0.1:${MOCK_PORT}`,
      WEB_ORIGIN,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout.pipe(log);
  server.stderr.pipe(log);
  await waitForServer(`${WEB_ORIGIN}/`, 30_000);

  return async () => {
    server.kill();
    await new Promise((resolve) => mock.close(resolve));
    log.end();
  };
}
