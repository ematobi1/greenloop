// The HUD globe's state, kept free of three.js so it can be unit-tested: what the core
// shows for the chat's state, what each orbiting node reports, and whether to animate.

import type { Health, ServiceStatus } from "./hud.ts";

export type CoreState = "idle" | "waiting" | "streaming" | "error";

export type ChatSignal = "send" | "delta" | "done" | "error" | "reset";

// The core pulses while a reply is pending, reacts to each streamed delta, and turns amber
// on error until the next send.
export function nextCoreState(current: CoreState, signal: ChatSignal): CoreState {
  switch (signal) {
    case "send":
      return "waiting";
    case "delta":
      return current === "error" ? "error" : "streaming";
    case "done":
      return current === "error" ? "error" : "idle";
    case "error":
      return "error";
    case "reset":
      return "idle";
  }
}

export type NodeLevel = "ok" | "warn" | "unknown";

export type GlobeNode = {
  id: string;
  label: string;
  // What the colour actually measures, shown next to the label so it never overclaims.
  basis: string;
  source: "orchestrator" | "broker" | "database";
};

export const GLOBE_NODES: readonly GlobeNode[] = [
  { id: "orchestrator", label: "Orchestrator", basis: "health check", source: "orchestrator" },
  { id: "broker", label: "Broker", basis: "health check", source: "broker" },
  { id: "memory", label: "Memory", basis: "database check", source: "database" },
  { id: "agents", label: "Agents", basis: "registry reachable", source: "orchestrator" },
  { id: "tools", label: "Tools", basis: "broker reachable", source: "broker" },
  { id: "approvals", label: "Approvals", basis: "broker reachable", source: "broker" },
];

const LEVELS: Record<ServiceStatus, NodeLevel> = {
  ok: "ok",
  unavailable: "warn",
  not_configured: "warn",
  unknown: "unknown",
};

export function nodeLevel(node: GlobeNode, health: Health | null): NodeLevel {
  const status = health?.services.find((service) => service.name === node.source)?.status;
  return status ? LEVELS[status] : "unknown";
}

export function nodeStatusText(node: GlobeNode, level: NodeLevel): string {
  const word = { ok: "up", warn: "degraded", unknown: "unknown" }[level];
  return `${node.label}: ${word} (${node.basis})`;
}

// Colours as numbers for three.js, matching the CSS tokens --hud-ok, --hud-warn, --hud-unknown.
export const LEVEL_COLOURS: Record<NodeLevel, number> = { ok: 0x3dffa8, warn: 0xffc15a, unknown: 0x7b8aa3 };
export const CORE_COLOURS: Record<CoreState, number> = {
  idle: 0x3dd6ff,
  waiting: 0x6f8bff,
  streaming: 0x9ff0ff,
  error: 0xffc15a,
};

export type MotionContext = { reducedMotion: boolean; hidden: boolean; narrow?: boolean };

// Reduced motion, and phone widths (battery), render one still frame; a hidden tab
// renders nothing at all.
export function renderMode({ reducedMotion, hidden, narrow = false }: MotionContext): "animate" | "still" | "paused" {
  if (hidden) return "paused";
  return reducedMotion || narrow ? "still" : "animate";
}

export const NARROW_QUERY = "(max-width: 767px)";

// Intensity of the core glow at time t (seconds) for a state; `burst` is 0..1 and decays
// after each streamed delta.
export function coreIntensity(state: CoreState, t: number, burst: number): number {
  switch (state) {
    case "idle":
      return 0.9;
    case "waiting":
      return 1.1 + 0.5 * Math.sin(t * 4);
    case "streaming":
      return 1.3 + 0.9 * burst;
    case "error":
      return 1.2;
  }
}

export const FRAME_BUDGET_MS = 1000 / 30;
