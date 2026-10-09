"use client";

import { healthSummary, serviceLabel, updatedLabel } from "@/lib/hud";

import { useHudData } from "../shell/HudData";
import { useNow } from "./useNow";

const RADIUS = 42;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

// System health ring: the share of services up, with plain words for each one.
export default function HealthPanel() {
  const { health } = useHudData();
  const now = useNow();
  const summary = healthSummary(health);
  const filled = summary.percent === null ? 0 : (summary.percent / 100) * CIRCUMFERENCE;
  return (
    <section className="hud-panel hud-health" aria-labelledby="health-title" data-level={summary.level}>
      <h2 id="health-title" className="hud-panel__title">
        System health
      </h2>
      <div className="hud-health__body">
        <svg className="hud-health__ring" viewBox="0 0 100 100" role="img" aria-label={`${summary.word}: ${summary.detail}`}>
          <circle cx="50" cy="50" r={RADIUS} className="hud-health__track" />
          <circle
            cx="50"
            cy="50"
            r={RADIUS}
            className="hud-health__fill"
            strokeDasharray={`${filled} ${CIRCUMFERENCE}`}
            transform="rotate(-90 50 50)"
          />
          <text x="50" y="50" className="hud-health__percent" textAnchor="middle" dominantBaseline="central">
            {summary.percent === null ? "—" : `${summary.percent}%`}
          </text>
        </svg>
        <div>
          <p className="hud-health__word">{summary.word}</p>
          <p className="hud-health__detail">{summary.detail}</p>
          <ul className="hud-health__services">
            {(health?.services ?? []).map((service) => (
              <li key={service.name} data-status={service.status}>
                <span className={`hud-dot ${service.status === "ok" ? "hud-dot--ok" : service.status === "unknown" ? "" : "hud-dot--warn"}`} aria-hidden="true" />
                {serviceLabel(service)}
              </li>
            ))}
          </ul>
          <p className="hud-updated">{now ? updatedLabel(health?.updated_at, now) : ""}</p>
        </div>
      </div>
    </section>
  );
}
