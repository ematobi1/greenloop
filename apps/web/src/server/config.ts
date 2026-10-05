// Server-only settings. Never import from a client component: the orchestrator URL
// must not reach the browser.

export type ServerConfig = {
  orchestratorUrl: string;
  webOrigin: string;
};

export function readServerConfig(env: Record<string, string | undefined>): ServerConfig {
  return {
    orchestratorUrl: httpUrl(env.ORCHESTRATOR_URL, "ORCHESTRATOR_URL").href.replace(/\/$/, ""),
    webOrigin: origin(env.WEB_ORIGIN),
  };
}

function httpUrl(value: string | undefined, name: string): URL {
  if (!value) throw new Error(`${name} is not set.`);
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${name} is not a valid URL.`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`${name} must be an http or https URL.`);
  }
  return url;
}

function origin(value: string | undefined): string {
  const url = httpUrl(value, "WEB_ORIGIN");
  if (url.origin !== value) {
    throw new Error("WEB_ORIGIN must be a bare origin such as http://127.0.0.1:3000.");
  }
  return url.origin;
}
