import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  GLOBE_NODES,
  coreIntensity,
  nextCoreState,
  nodeLevel,
  nodeStatusText,
  renderMode,
} from "../src/lib/globe.ts";

const health = (statuses) => ({
  services: Object.entries(statuses).map(([name, status]) => ({ name, status })),
  up: 0,
  total: 3,
  updated_at: "",
});

test("the core goes waiting, streaming, then idle over a reply", () => {
  let state = "idle";
  for (const [signal, expected] of [
    ["send", "waiting"],
    ["delta", "streaming"],
    ["delta", "streaming"],
    ["done", "idle"],
  ]) {
    state = nextCoreState(state, signal);
    assert.equal(state, expected, signal);
  }
});

test("an error stays amber until the next send", () => {
  let state = nextCoreState("streaming", "error");
  assert.equal(state, "error");
  assert.equal(nextCoreState(state, "delta"), "error");
  assert.equal(nextCoreState(state, "done"), "error");
  assert.equal(nextCoreState(state, "send"), "waiting");
  assert.equal(nextCoreState(state, "reset"), "idle");
});

test("the core pulses while waiting and reacts to deltas, and is steady otherwise", () => {
  assert.notEqual(coreIntensity("waiting", 0.1, 0), coreIntensity("waiting", 0.5, 0));
  assert.ok(coreIntensity("streaming", 0, 1) > coreIntensity("streaming", 0, 0));
  assert.equal(coreIntensity("idle", 0, 1), coreIntensity("idle", 9, 0));
  assert.equal(coreIntensity("error", 0, 1), coreIntensity("error", 9, 0));
});

test("nodes take their colour from the service they actually measure", () => {
  const h = health({ orchestrator: "ok", broker: "unavailable", database: "ok" });
  const levels = Object.fromEntries(GLOBE_NODES.map((node) => [node.id, nodeLevel(node, h)]));
  assert.deepEqual(levels, { orchestrator: "ok", broker: "warn", memory: "ok", agents: "ok", tools: "warn", approvals: "warn" });
  assert.ok(GLOBE_NODES.every((node) => nodeLevel(node, null) === "unknown"));
});

test("derived nodes say what they really check", () => {
  const basis = Object.fromEntries(GLOBE_NODES.map((node) => [node.id, node.basis]));
  assert.equal(basis.agents, "registry reachable");
  assert.equal(basis.tools, "broker reachable");
  assert.equal(basis.approvals, "broker reachable");
  assert.equal(nodeStatusText(GLOBE_NODES[3], "ok"), "Agents: up (registry reachable)");
});

test("reduced motion renders a still frame and a hidden tab renders nothing", () => {
  assert.equal(renderMode({ reducedMotion: false, hidden: false }), "animate");
  assert.equal(renderMode({ reducedMotion: true, hidden: false }), "still");
  assert.equal(renderMode({ reducedMotion: true, hidden: true }), "paused");
  assert.equal(renderMode({ reducedMotion: false, hidden: true }), "paused");
});

test("three.js is loaded lazily and only by the globe", () => {
  const source = readFileSync(new URL("../src/components/hud/HudGlobe.tsx", import.meta.url), "utf8");
  assert.match(source, /import\("three"\)/);
  assert.doesNotMatch(source, /^import .* from "three";$/m);
});
