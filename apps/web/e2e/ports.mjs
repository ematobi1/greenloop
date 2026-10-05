// Fixed loopback ports for the end-to-end run, away from the dev stack's defaults.
export const WEB_PORT = 53900;
export const MOCK_PORT = 53999;
export const WEB_ORIGIN = `http://127.0.0.1:${WEB_PORT}`;
export const SERVER_LOG = new URL("../test-results/next-server.log", import.meta.url);
