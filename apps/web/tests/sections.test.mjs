import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { SECTIONS, sectionBySlug } from "../src/app/sections.ts";

const appDir = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "app", "(hud)");
const EXPECTED = ["chat", "memory", "plans", "approvals", "agents", "workflows", "audit", "settings"];

test("sections cover the eight areas in nav order", () => {
  assert.deepEqual(
    SECTIONS.map((section) => section.slug),
    EXPECTED,
  );
});

const BUILT = new Set(["chat", "memory", "plans"]);

test("every unbuilt section has a placeholder page that renders its own slug", () => {
  for (const { slug } of SECTIONS.filter(({ slug }) => !BUILT.has(slug))) {
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

test("the memory page renders the memory app", () => {
  assert.match(readFileSync(join(appDir, "memory", "page.tsx"), "utf8"), /<MemoryApp /);
});

test("the plans page renders the plans app", () => {
  assert.match(readFileSync(join(appDir, "plans", "page.tsx"), "utf8"), /<PlansApp /);
});

test("the chat page renders the chat app", () => {
  assert.match(readFileSync(join(appDir, "chat", "page.tsx"), "utf8"), /<ChatApp /);
});

test("sectionBySlug rejects unknown slugs", () => {
  assert.equal(sectionBySlug("audit").title, "Audit");
  assert.throws(() => sectionBySlug("admin"), /Unknown section/);
});

test("the shell builds its tabs and rail from SECTIONS", () => {
  const nav = readFileSync(join(appDir, "..", "..", "components", "shell", "Nav.tsx"), "utf8");
  assert.equal(nav.match(/SECTIONS\.map/g).length, 2);
  assert.match(nav, /aria-label="Main"/);
});

test("signed-in pages sit behind a cookie check and / goes to /chat", () => {
  assert.ok(readFileSync(join(appDir, "layout.tsx"), "utf8").includes('redirect("/sign-in")'));
  assert.ok(readFileSync(join(appDir, "..", "page.tsx"), "utf8").includes('redirect("/chat")'));
});
