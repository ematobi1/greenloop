import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// WCAG AA from the real token values (ADR 0014): 4.5:1 for text on the darkest page
// background and on the solid panel colour. Computed, never eyeballed.
const css = readFileSync(new URL("../src/styles/tokens.css", import.meta.url), "utf8");
const token = (name) => {
  const match = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
  assert.ok(match, `missing hex token ${name}`);
  return match[1];
};

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const linear = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

export function contrast(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const TEXT = ["--hud-text", "--hud-text-muted", "--hud-accent", "--hud-ok", "--hud-warn", "--hud-error-text"];
const BACKGROUNDS = ["--hud-bg", "--hud-panel-solid"];

test("every text colour meets 4.5:1 on every background", () => {
  for (const text of TEXT) {
    for (const background of BACKGROUNDS) {
      const ratio = contrast(token(text), token(background));
      assert.ok(ratio >= 4.5, `${text} on ${background} is ${ratio.toFixed(2)}:1`);
    }
  }
});

test("text on accent buttons meets 4.5:1", () => {
  assert.ok(contrast(token("--hud-text-on-accent"), token("--hud-accent")) >= 4.5);
});

test("the contrast helper matches known ratios", () => {
  assert.equal(contrast("#000000", "#ffffff").toFixed(1), "21.0");
  assert.equal(contrast("#777777", "#ffffff").toFixed(2), "4.48");
});

test("the globe's three.js colours are the CSS tokens they name", async () => {
  const { THEME_COLOURS } = await import("../src/lib/globe.ts");
  for (const [name, value] of Object.entries(THEME_COLOURS)) {
    assert.equal(`#${value.toString(16).padStart(6, "0")}`, token(name).toLowerCase(), name);
  }
});

test("channel tokens match their hex tokens", () => {
  const channels = (name) => new RegExp(`${name}:\\s*(\\d+) (\\d+) (\\d+);`).exec(css).slice(1).map(Number);
  const hex = (name) => [1, 3, 5].map((i) => parseInt(token(name).slice(i, i + 2), 16));
  assert.deepEqual(channels("--hud-accent-rgb"), hex("--hud-accent"));
  assert.deepEqual(channels("--hud-accent-2-rgb"), hex("--hud-accent-2"));
  assert.deepEqual(channels("--hud-core-hot-rgb"), hex("--hud-core-hot"));
  assert.deepEqual(channels("--hud-panel-rgb"), hex("--hud-panel-solid"));
});

test("styles and the globe take colours from tokens, never raw values", () => {
  const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
  assert.doesNotMatch(read("../src/app/globals.css"), /rgba?\(\s*\d|#[0-9a-fA-F]{3,8}\b/);
  assert.doesNotMatch(read("../src/components/hud/HudGlobe.tsx"), /0x[0-9a-fA-F]{6}/);
});

test("motion tokens drop to zero for reduced motion", () => {
  assert.match(css, /prefers-reduced-motion: reduce\)\s*\{\s*:root\s*\{\s*--hud-fast: 0ms;\s*--hud-slow: 0ms;/);
});
