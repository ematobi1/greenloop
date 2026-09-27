import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { SECTIONS, sectionBySlug } from "../src/app/sections.ts";

const appDir = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "app");
const EXPECTED = ["chat", "memory", "approvals", "agents", "workflows", "audit", "settings"];

test("sections cover the seven planned areas in nav order", () => {
  assert.deepEqual(
    SECTIONS.map((section) => section.slug),
    EXPECTED,
  );
});

test("every section has a page that renders its own slug", () => {
  for (const { slug } of SECTIONS) {
    const page = join(appDir, slug, "page.tsx");
    assert.ok(existsSync(page), `missing ${page}`);
    assert.match(readFileSync(page, "utf8"), new RegExp(`slug="${slug}"`));
  }
});

test("every section names a roadmap phase between 2 and 5", () => {
  for (const section of SECTIONS) {
    assert.ok(Number.isInteger(section.phase) && section.phase >= 2 && section.phase <= 5);
    assert.ok(section.title.length > 0 && section.summary.length > 0);
  }
});

test("sectionBySlug rejects unknown slugs", () => {
  assert.equal(sectionBySlug("audit").title, "Audit");
  assert.throws(() => sectionBySlug("admin"), /Unknown section/);
});

test("layout builds its nav from SECTIONS", () => {
  const layout = readFileSync(join(appDir, "layout.tsx"), "utf8");
  assert.match(layout, /SECTIONS\.map/);
  assert.match(layout, /aria-label="Main"/);
});
