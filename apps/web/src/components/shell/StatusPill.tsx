"use client";

// Filled in by the health step (ADR 0014): "System online" only when every check is up.
export default function StatusPill() {
  return (
    <span className="hud-pill" role="status">
      <span className="hud-dot" aria-hidden="true" />
      System status
    </span>
  );
}
