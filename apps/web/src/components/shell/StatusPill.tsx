"use client";

import { healthSummary } from "@/lib/hud";

import { useHudData } from "./HudData";

// "System online" only when every service is up; partial outages read as degraded (amber).
export default function StatusPill() {
  const { health } = useHudData();
  const summary = healthSummary(health);
  const dot = summary.level === "ok" ? "hud-dot--ok" : summary.level === "unknown" ? "" : "hud-dot--warn";
  return (
    <span className="hud-pill" role="status" title={summary.detail}>
      <span className={`hud-dot ${dot}`} aria-hidden="true" />
      {summary.word}
    </span>
  );
}
