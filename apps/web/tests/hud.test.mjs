import assert from "node:assert/strict";
import { test } from "node:test";

import { KPIS, healthSummary, kpiView, serviceLabel, updatedLabel } from "../src/lib/hud.ts";

const spec = (key) => KPIS.find((item) => item.key === key);
const health = (statuses) => {
  const services = Object.entries(statuses).map(([name, status]) => ({ name, status }));
  return { services, up: services.filter((s) => s.status === "ok").length, total: services.length, updated_at: "" };
};

test("the six tiles are the agreed ones, in order", () => {
  assert.deepEqual(
    KPIS.map((item) => item.key),
    ["conversations", "memories", "plan_drafts", "pending_approvals", "agents", "health"],
  );
});

test("a tile shows its real count", () => {
  const overview = { tiles: { memories: { value: 1234, note: null } }, updated_at: "" };
  assert.deepEqual(kpiView(spec("memories"), overview, null), { label: "Memories", value: "1,234", detail: "" });
  assert.equal(kpiView(spec("memories"), { tiles: { memories: { value: 0, note: null } }, updated_at: "" }, null).value, "0");
});

test("missing or failed data shows a dash with the reason, never a number", () => {
  assert.deepEqual(kpiView(spec("agents"), null, null), { label: "Agents", value: "—", detail: "No data right now" });
  const failed = { tiles: { agents: { value: null, note: "Unavailable right now" } }, updated_at: "" };
  assert.deepEqual(kpiView(spec("agents"), failed, null), { label: "Agents", value: "—", detail: "Unavailable right now" });
  assert.deepEqual(kpiView({ key: "workflows", label: "Workflows", arrives: 4 }, null, null), {
    label: "Workflows",
    value: "—",
    detail: "Arrives in Phase 4",
  });
});

test("health reads as online, degraded or offline, with the count of services up", () => {
  assert.deepEqual(healthSummary(health({ orchestrator: "ok", broker: "ok", database: "ok" })), {
    level: "ok",
    percent: 100,
    detail: "3 of 3 services up",
    word: "System online",
  });
  const brokerDown = healthSummary(health({ orchestrator: "ok", broker: "unavailable", database: "ok" }));
  assert.deepEqual([brokerDown.level, brokerDown.percent, brokerDown.detail, brokerDown.word], [
    "degraded",
    67,
    "2 of 3 services up",
    "System degraded",
  ]);
  assert.equal(healthSummary(health({ orchestrator: "unavailable", broker: "unknown", database: "unknown" })).level, "offline");
  assert.deepEqual(healthSummary(null), { level: "unknown", percent: null, detail: "No status right now", word: "System status unknown" });
  assert.equal(kpiView(spec("health"), null, null).value, "—");
});

test("service labels and update times are plain words", () => {
  assert.equal(serviceLabel({ name: "broker", status: "not_configured" }), "Broker: not configured");
  const now = new Date("2026-10-08T12:00:00Z");
  assert.equal(updatedLabel(undefined, now), "Not updated yet");
  assert.equal(updatedLabel("2026-10-08T11:59:55Z", now), "Updated just now");
  assert.equal(updatedLabel("2026-10-08T11:59:30Z", now), "Updated 30 s ago");
  assert.equal(updatedLabel("2026-10-08T11:55:00Z", now), "Updated 5 min ago");
});
