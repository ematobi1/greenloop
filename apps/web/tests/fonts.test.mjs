import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

const fonts = new URL("../src/fonts/", import.meta.url);
const readme = readFileSync(new URL("README.md", fonts), "utf8");

test("every bundled woff2 matches the SHA256 recorded in the fonts README", () => {
  const files = readdirSync(new URL("orbitron/", fonts)).filter((name) => name.endsWith(".woff2"));
  assert.deepEqual(files.sort(), ["orbitron-latin-500-normal.woff2", "orbitron-latin-700-normal.woff2"]);
  for (const name of files) {
    const hash = createHash("sha256").update(readFileSync(new URL(`orbitron/${name}`, fonts))).digest("hex");
    const row = readme.split("\n").find((line) => line.includes(`orbitron/${name}`));
    assert.ok(row, `${name} is listed in the README`);
    assert.ok(row.includes(hash), `${name} hash ${hash} matches the README`);
  }
});

test("the README names the source package and the licence sits beside the fonts", () => {
  assert.match(readme, /@fontsource\/orbitron@5\.3\.0/);
  assert.match(readFileSync(new URL("orbitron/OFL.txt", fonts), "utf8"), /SIL OPEN FONT LICENSE/i);
});
