import { expect, test, type Page } from "@playwright/test";

import { E2E_PASSWORD, E2E_USERNAME } from "./mock-orchestrator.mjs";
import { MOCK_PORT } from "./ports.mjs";

// Screenshots for review land here (gitignored): apps/web/test-results/screenshots/.
const SHOTS = "test-results/screenshots";
const MOCK = `http://127.0.0.1:${MOCK_PORT}`;

test.describe.configure({ mode: "serial" });

async function signIn(page: Page) {
  await page.goto("/sign-in");
  await page.getByLabel("Username").fill(E2E_USERNAME);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

async function frames(page: Page): Promise<number> {
  return Number((await page.locator(".hud-globe").getAttribute("data-frames")) ?? "0");
}

test.afterEach(async ({ request }) => {
  await request.post(`${MOCK}/__broker?status=ok`);
  await request.post(`${MOCK}/__fail?path=`);
});

test("the sign-in page matches the HUD", async ({ page }) => {
  await page.goto("/sign-in");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.locator(".sign-in.hud-panel")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/sign-in.png`, fullPage: true });
});

test("the user menu shows the real signed-in username", async ({ page }) => {
  await signIn(page);
  await expect(page.getByRole("button", { name: /Signed in as/ })).toHaveText(`Signed in as ${E2E_USERNAME}`);
});

test("KPI tiles show real counts, and a dash with the reason when a source fails", async ({ page, request }) => {
  await signIn(page);
  const tile = (key: string) => page.locator(`[data-kpi="${key}"]`);
  await expect(tile("agents").locator(".hud-kpi__value")).toHaveText("3");
  await expect(tile("pending_approvals").locator(".hud-kpi__value")).toHaveText("0");
  await expect(page.locator(".hud-kpis .hud-updated")).toContainText(/Updated/);

  await request.post(`${MOCK}/__fail?path=/v1/approvals`);
  await page.reload();
  await expect(tile("pending_approvals").locator(".hud-kpi__value")).toHaveText("—");
  await expect(tile("pending_approvals").locator(".hud-kpi__detail")).toHaveText("Unavailable right now");
  await expect(tile("agents").locator(".hud-kpi__value")).toHaveText("3");
});

test("a broker outage reads as degraded, in amber, with the count of services up", async ({ page, request }) => {
  await signIn(page);
  await expect(page.locator(".hud-pill")).toHaveText("System online");
  await request.post(`${MOCK}/__broker?status=unavailable`);
  await page.reload();
  await expect(page.locator(".hud-pill")).toHaveText("System degraded");
  const panel = page.locator(".hud-health");
  await expect(panel).toHaveAttribute("data-level", "degraded");
  await expect(panel).toContainText("2 of 3 services up");
  await expect(panel).toContainText("Broker: down");
  await expect(page.locator(".hud-node", { hasText: "Tools" })).toHaveClass(/hud-node--warn/);
  await expect(page.locator(".hud-node", { hasText: "Tools" })).toContainText("broker reachable");
});

test.describe("with motion", () => {
  test.use({ contextOptions: { reducedMotion: "no-preference" } });

  test("the globe animates, follows the reply, and screenshots the idle and streaming HUD", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await signIn(page);
    const globe = page.locator(".hud-globe");
    await expect(globe).toHaveAttribute("data-globe", /ready|fallback/);
    test.skip((await globe.getAttribute("data-globe")) === "fallback", "WebGL unavailable in this browser");
    await expect(globe).toHaveAttribute("data-motion", "animate");
    const before = await frames(page);
    await page.waitForTimeout(800);
    expect(await frames(page)).toBeGreaterThan(before);
    await expect(globe).toHaveAttribute("data-core-state", "idle");
    await page.screenshot({ path: `${SHOTS}/hud-idle.png` });

    await page.getByLabel("Message", { exact: true }).fill("hello");
    await page.getByLabel("Message", { exact: true }).press("Enter");
    await expect(globe).toHaveAttribute("data-core-state", /waiting|streaming/);
    await expect(page.locator(".message--streaming")).toContainText("Hello");
    await expect(globe).toHaveAttribute("data-core-state", "streaming");
    await page.screenshot({ path: `${SHOTS}/hud-streaming.png`, fullPage: true });
    await expect(page.locator(".message--streaming")).toHaveCount(0);
    await expect(globe).toHaveAttribute("data-core-state", "idle");
  });

  test("the motion can be paused and resumed, and nodes hold still under focus", async ({ page }) => {
    await signIn(page);
    const globe = page.locator(".hud-globe");
    await expect(globe).toHaveAttribute("data-globe", /ready|fallback/);
    test.skip((await globe.getAttribute("data-globe")) === "fallback", "WebGL unavailable in this browser");
    await page.getByRole("button", { name: "Pause motion" }).click();
    await expect(globe).toHaveAttribute("data-motion", "still");
    const still = await frames(page);
    await page.waitForTimeout(600);
    expect(await frames(page)).toBe(still);
    await page.getByRole("button", { name: "Resume motion" }).click();
    await expect(globe).toHaveAttribute("data-motion", "animate");

    const node = page.getByRole("button", { name: /^Broker:/ });
    await node.focus();
    const at = await node.evaluate((element) => element.style.transform);
    await page.waitForTimeout(600);
    expect(await node.evaluate((element) => element.style.transform)).toBe(at);
  });

  test("a hidden tab stops drawing the globe", async ({ page }) => {
    await signIn(page);
    const globe = page.locator(".hud-globe");
    await expect(globe).toHaveAttribute("data-globe", /ready|fallback/);
    test.skip((await globe.getAttribute("data-globe")) === "fallback", "WebGL unavailable in this browser");
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect(globe).toHaveAttribute("data-motion", "paused");
    const paused = await frames(page);
    await page.waitForTimeout(600);
    expect(await frames(page)).toBe(paused);
  });
});

test("reduced motion draws one still globe and no animation", async ({ page }) => {
  await signIn(page);
  const globe = page.locator(".hud-globe");
  await expect(globe).toHaveAttribute("data-globe", /ready|fallback/);
  if ((await globe.getAttribute("data-globe")) === "ready") {
    await expect(globe).toHaveAttribute("data-motion", "still");
    const still = await frames(page);
    await page.waitForTimeout(800);
    expect(await frames(page)).toBe(still);
  }
  await expect(page.locator(".hud-node")).toHaveCount(6);
});

test("everything is reachable from the keyboard", async ({ page }) => {
  await signIn(page);
  const reached = new Set<string>();
  for (let step = 0; step < 80 && !reached.has("message-draft"); step++) {
    await page.keyboard.press("Tab");
    const id = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      return element?.id || element?.getAttribute("aria-label") || element?.textContent?.trim() || "";
    });
    reached.add(id);
  }
  expect(reached.has("Chat")).toBe(true);
  expect([...reached].some((name) => name.startsWith("Signed in as"))).toBe(true);
  expect([...reached].some((name) => name.startsWith("Orchestrator:"))).toBe(true);
  expect(reached.has("message-draft")).toBe(true);
});

test("the Memory page and the mobile HUD screenshots", async ({ page }) => {
  await signIn(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Memory" }).click();
  await expect(page.getByRole("heading", { name: "Memory" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/memory.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Chat" }).click();
  await expect(page.locator(".hud-kpi")).toHaveCount(6);
  // overflow-x is hidden on body, so measure how wide the layout really is, not the scroll width.
  const widest = await page.evaluate(() =>
    Math.max(...[...document.querySelectorAll(".hud-shell, .hud-main, .hud-kpis, .hud__grid, .hud-topbar")].map((el) => el.getBoundingClientRect().right)),
  );
  expect(widest).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `${SHOTS}/hud-mobile.png`, fullPage: true });
});

test("replies are announced, and the thread follows the newest message", async ({ page }) => {
  await signIn(page);
  const field = page.getByLabel("Message", { exact: true });
  for (let turn = 1; turn <= 6; turn++) {
    await field.fill(`message ${turn}`);
    await field.press("Enter");
    await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
    await expect(page.locator(".message--streaming")).toHaveCount(0);
  }
  await expect(page.locator("[data-reply-announcement]")).toContainText("GreenLoop replied:");
  const list = page.locator(".chat__messages");
  await expect(list.locator(".message--user").last()).toContainText("message 6");
  const gap = await list.evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight);
  expect(gap).toBeLessThan(4);
});

test("the Plans page lists drafts and can discard them", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Start a conversation" }).click();
  await page.getByLabel("Goal to plan").fill("Tidy the garage");
  await page.getByRole("button", { name: "Draft a plan" }).click();
  await expect(page.getByRole("article", { name: "Draft plan" })).toBeVisible();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Plans" }).click();
  const item = page.locator(".plans__item", { hasText: "Tidy the garage" });
  await expect(item).toHaveAttribute("data-status", "draft");
  await item.getByRole("button", { name: "Discard plan" }).click();
  await expect(item).toHaveAttribute("data-status", "discarded");
});

test("an expired session goes back to sign-in with a note", async ({ page, request }) => {
  await signIn(page);
  await request.post(`${MOCK}/__revoke`);
  // Any request now gets 401: the next background poll or this reload, whichever is first.
  await page.reload();
  await expect(page).toHaveURL(/\/sign-in\?expired=1$/);
  await expect(page.locator(".sign-in__error")).toHaveText("Your session has ended. Sign in again.");
});
