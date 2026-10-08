// HUD data: the shapes /api/overview and /api/health return, and the pure rules that turn
// them into what the HUD shows. No guessing: a missing value stays missing.

export type Tile = { value: number | null; note: string | null };
export type Overview = { tiles: Record<string, Tile>; updated_at: string };

export type ServiceStatus = "ok" | "unavailable" | "not_configured" | "unknown";
export type Service = { name: string; status: ServiceStatus };
export type Health = { services: Service[]; up: number; total: number; updated_at: string };

export type HealthLevel = "ok" | "degraded" | "offline" | "unknown";

export const REFRESH_MS = 30_000;

export type KpiSpec = { key: string; label: string; arrives?: number };

// The six tiles across the top. `arrives` marks data that has no API yet.
export const KPIS: readonly KpiSpec[] = [
  { key: "conversations", label: "Conversations" },
  { key: "memories", label: "Memories" },
  { key: "plan_drafts", label: "Plan drafts" },
  { key: "pending_approvals", label: "Pending approvals" },
  { key: "agents", label: "Agents" },
  { key: "health", label: "Health" },
];

export type KpiView = { label: string; value: string; detail: string };

export function kpiView(spec: KpiSpec, overview: Overview | null, health: Health | null): KpiView {
  if (spec.key === "health") {
    const summary = healthSummary(health);
    return {
      label: spec.label,
      value: summary.percent === null ? "—" : `${summary.percent}%`,
      detail: summary.detail,
    };
  }
  if (spec.arrives) return { label: spec.label, value: "—", detail: `Arrives in Phase ${spec.arrives}` };
  const tile = overview?.tiles[spec.key];
  if (!tile || tile.value === null) {
    return { label: spec.label, value: "—", detail: tile?.note ?? "Not loaded yet" };
  }
  return { label: spec.label, value: tile.value.toLocaleString(), detail: "" };
}

export type HealthSummary = {
  level: HealthLevel;
  percent: number | null;
  detail: string;
  word: string;
};

const NAMES: Record<string, string> = { orchestrator: "Orchestrator", broker: "Broker", database: "Database" };

export function serviceLabel(service: Service): string {
  const name = NAMES[service.name] ?? service.name;
  const state = {
    ok: "up",
    unavailable: "down",
    not_configured: "not configured",
    unknown: "unknown",
  }[service.status];
  return `${name}: ${state}`;
}

// Calm wording on purpose: a partial outage is "degraded" (amber), never an alarm.
export function healthSummary(health: Health | null): HealthSummary {
  if (!health || health.total === 0) {
    return { level: "unknown", percent: null, detail: "Checking services…", word: "System status unknown" };
  }
  const percent = Math.round((health.up / health.total) * 100);
  const detail = `${health.up} of ${health.total} services up`;
  const orchestrator = health.services.find((service) => service.name === "orchestrator");
  if (health.up === health.total) return { level: "ok", percent, detail, word: "System online" };
  if (orchestrator?.status !== "ok") return { level: "offline", percent, detail, word: "System offline" };
  return { level: "degraded", percent, detail, word: "System degraded" };
}

export function updatedLabel(iso: string | undefined, now: Date): string {
  if (!iso) return "Not updated yet";
  const seconds = Math.max(0, Math.round((now.getTime() - Date.parse(iso)) / 1000));
  if (seconds < 10) return "Updated just now";
  if (seconds < 60) return `Updated ${seconds} s ago`;
  return `Updated ${Math.round(seconds / 60)} min ago`;
}
