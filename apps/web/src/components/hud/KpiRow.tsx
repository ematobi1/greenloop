"use client";

import { KPIS, kpiView, updatedLabel } from "@/lib/hud";

import { useHudData } from "../shell/HudData";
import { useNow } from "./useNow";

// The six KPI tiles. Every number comes from an API; anything missing shows "—" and why.
export default function KpiRow() {
  const { overview, health } = useHudData();
  const now = useNow();
  return (
    <section className="hud-kpis" aria-label="Key figures">
      <ul className="hud-kpis__list">
        {KPIS.map((spec) => {
          const view = kpiView(spec, overview, health);
          return (
            <li key={spec.key} className="hud-panel hud-kpi" data-kpi={spec.key}>
              <span className="hud-label">{view.label}</span>
              <span className="hud-kpi__value">{view.value}</span>
              <span className="hud-kpi__detail">{view.detail}</span>
            </li>
          );
        })}
      </ul>
      <p className="hud-updated">{now ? updatedLabel(overview?.updated_at, now) : ""}</p>
    </section>
  );
}
