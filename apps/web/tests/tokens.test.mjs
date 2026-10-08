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

test("motion tokens drop to zero for reduced motion", () => {
  assert.match(css, /prefers-reduced-motion: reduce\)\s*\{\s*:root\s*\{\s*--hud-fast: 0ms;\s*--hud-slow: 0ms;/);
});
