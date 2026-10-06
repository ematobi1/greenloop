import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import { E2E_PASSWORD, E2E_TOKEN, E2E_USERNAME } from "./mock-orchestrator.mjs";
import { MOCK_PORT, SERVER_LOG, WEB_ORIGIN } from "./ports.mjs";

const COOKIE = "__Host-greenloop_session";

// Every response the browser receives is checked: the token must never come back.
function watchForToken(page: Page): string[] {
  const leaks: string[] = [];
  page.on("response", async (response) => {
    const headers = await response.allHeaders().catch(() => ({}) as Record<string, string>);
    for (const [name, value] of Object.entries(headers)) {
      if (name === "set-cookie") continue;
      if (value.includes(E2E_TOKEN)) leaks.push(`${response.url()} header ${name}`);
    }
    const body = await response.text().catch(() => "");
    if (body.includes(E2E_TOKEN)) leaks.push(`${response.url()} body`);
  });
  return leaks;
}

async function signIn(page: Page, username = E2E_USERNAME, password = E2E_PASSWORD) {
  await page.goto("/chat");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test.describe.configure({ mode: "serial" });

test("a wrong password is refused, clears the field and sets no cookie", async ({ page, context }) => {
  await signIn(page, E2E_USERNAME, "not the password");
  await expect(page.locator(".sign-in__error")).toHaveText("Wrong username or password.");
  await expect(page.getByLabel("Password")).toHaveValue("");
  expect(await context.cookies()).toEqual([]);
});

test("a locked username is told to wait", async ({ page, context }) => {
  await signIn(page, "locked", "anything at all");
  await expect(page.locator(".sign-in__error")).toContainText("Too many sign-in attempts");
  expect(await context.cookies()).toEqual([]);
});

test("the sign-in form never offers token paste", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByText(/API token/i)).toHaveCount(0);
  await expect(page.getByLabel("Password")).toHaveAttribute("autocomplete", "current-password");
});

test("signing in sets a locked-down cookie that page scripts can't read", async ({ page, context }) => {
  const leaks = watchForToken(page);
  await signIn(page);
  await expect(page.getByRole("button", { name: "Start a conversation" })).toBeVisible();

  const [cookie] = (await context.cookies()).filter((item) => item.name === COOKIE);
  expect(cookie).toMatchObject({ httpOnly: true, secure: true, sameSite: "Strict", path: "/" });
  expect(cookie.value.startsWith(E2E_TOKEN)).toBe(true);
  expect(await page.content()).not.toContain(E2E_PASSWORD);
  const lifetime = cookie.expires - Date.now() / 1000;
  expect(lifetime).toBeGreaterThan(12 * 3600 - 120);
  expect(lifetime).toBeLessThanOrEqual(12 * 3600);

  expect(await page.evaluate(() => document.cookie)).not.toContain(E2E_TOKEN);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).toBe("{}");
  expect(page.url()).not.toContain(E2E_TOKEN);
  await page.reload();
  await expect(page.getByRole("button", { name: "Start a conversation" })).toBeVisible();
  expect(await page.content()).not.toContain(E2E_TOKEN);
  expect(await page.content()).not.toContain(String(MOCK_PORT));
  expect(leaks).toEqual([]);
});

test("a reply streams in piece by piece, then is stored", async ({ page }) => {
  const leaks = watchForToken(page);
  await signIn(page);
  await page.getByRole("button", { name: "Start a conversation" }).click();
  await page.getByLabel("Message", { exact: true }).fill("hello");
  await page.getByLabel("Message", { exact: true }).press("Enter");

  const live = page.locator('[aria-live="polite"]');
  await expect(live).toHaveText("Hello");
  await expect(live).toHaveText("Hello from");
  await expect(page.locator(".message--assistant .message__text")).toHaveText("Hello from GreenLoop");
  await expect(live).toHaveCount(0);
  await expect(page.locator(".message--user .message__text")).toHaveText("hello");
  await expect(page.getByLabel("Message", { exact: true })).toHaveValue("");

  await page.reload();
  await page.getByRole("button", { name: "Start a conversation" }).waitFor();
  await page.locator(".chat__conversation").first().click();
  await expect(page.locator(".message__text")).toHaveText(["hello", "Hello from GreenLoop"]);
  expect(leaks).toEqual([]);
});

test("HTML in a reply is shown as text and never runs", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Start a conversation" }).click();
  await page.getByLabel("Message", { exact: true }).fill("html please");
  await page.getByRole("button", { name: "Send" }).click();
  // Wait for the stored reply, not the streaming preview, which is always plain text.
  await expect(page.locator('[aria-live="polite"]')).toHaveCount(0);
  const reply = page.locator(".message--assistant .message__text");
  await expect(reply).toHaveCount(1);
  await expect(reply).toHaveText('<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>');
  expect(await reply.evaluate((element) => element.children.length)).toBe(0);
  expect(await page.locator(".chat__messages img, .chat__messages script").count()).toBe(0);
  expect(await page.evaluate(() => (window as { __pwned?: number }).__pwned)).toBeUndefined();
});

test("busy and not-configured errors show their own messages and keep the draft", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Start a conversation" }).click();
  const alert = page.locator(".chat__error");

  await page.getByLabel("Message", { exact: true }).fill("busy");
  await page.getByLabel("Message", { exact: true }).press("Enter");
  await expect(alert).toContainText("A reply is still being written in this conversation");
  await expect(page.getByLabel("Message", { exact: true })).toHaveValue("busy");

  await page.getByLabel("Message", { exact: true }).fill("no ai");
  await page.getByLabel("Message", { exact: true }).press("Enter");
  await expect(alert).toContainText("No AI provider is configured");
});

test("a message can be saved to memory once", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Start a conversation" }).click();
  await page.getByLabel("Message", { exact: true }).fill("I prefer green tea");
  await page.getByLabel("Message", { exact: true }).press("Enter");
  await expect(page.locator('[aria-live="polite"]')).toHaveCount(0);
  const userMessage = page.locator(".message--user");
  await userMessage.getByRole("button", { name: "Remember" }).click();
  await expect(page.locator(".chat__notice")).toHaveText("Saved to memory.");
  await expect(userMessage.getByText("Saved to memory")).toBeVisible();
  await expect(userMessage.getByRole("button", { name: "Remember" })).toHaveCount(0);
  await expect(page.locator(".chat__error")).toHaveText("");
});

test("a long conversation opens on its latest messages", async ({ page, request }) => {
  await request.post(`http://127.0.0.1:${MOCK_PORT}/__seed-long`);
  await signIn(page);
  await page.getByRole("button", { name: "Long conversation" }).click();
  const texts = page.locator(".message__text");
  await expect(texts).toHaveCount(100);
  await expect(texts.first()).toHaveText("Message 51");
  await expect(texts.last()).toHaveText("Message 150");
  await expect(page.getByText("50 earlier messages aren't shown.")).toBeVisible();
  await expect(page.locator(".chat__error")).toHaveText("");
});

test("security headers are on pages and API routes", async ({ request }) => {
  for (const path of ["/", "/chat", "/api/conversations"]) {
    const response = await request.get(path);
    const headers = response.headers();
    expect(headers["x-frame-options"], path).toBe("DENY");
    expect(headers["content-security-policy"], path).toContain("frame-ancestors 'none'");
    expect(headers["x-content-type-options"], path).toBe("nosniff");
    expect(headers["referrer-policy"], path).toBe("no-referrer");
    expect(headers["x-powered-by"], path).toBeUndefined();
  }
});

test("cross-site and form-encoded writes are refused", async ({ request }) => {
  const forged = await request.post("/api/session", {
    headers: { Origin: "http://evil.example", "Content-Type": "application/json" },
    data: { username: E2E_USERNAME, password: E2E_PASSWORD },
  });
  expect(forged.status()).toBe(403);
  const form = await request.post("/api/session", {
    headers: { Origin: WEB_ORIGIN },
    form: { username: E2E_USERNAME, password: E2E_PASSWORD },
  });
  expect(form.status()).toBe(415);
  expect(forged.headers()["set-cookie"]).toBeUndefined();
});

test("sign-out clears the cookie and returns to sign-in", async ({ page, context }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.locator(".sign-in__error")).toHaveText("You're signed out.");
  expect((await context.cookies()).filter((item) => item.name === COOKIE)).toEqual([]);
});

test("sign out everywhere ends the other browser's session too", async ({ page, context, browser }) => {
  await signIn(page);
  const other = await browser.newContext();
  const otherPage = await other.newPage();
  await signIn(otherPage);
  await expect(otherPage.getByRole("button", { name: "Start a conversation" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out everywhere" }).click();
  await expect(page.locator(".sign-in__error")).toHaveText("You're signed out on every device.");
  expect((await context.cookies()).filter((item) => item.name === COOKIE)).toEqual([]);
  await otherPage.reload();
  await expect(otherPage.locator(".sign-in__error")).toHaveText("Your session has ended. Sign in again.");
  await other.close();
});

// Revokes every session on the mock; later tests sign in again.
test("a token revoked on the server sends the user back to sign-in", async ({ page, context, request }) => {
  await signIn(page);
  await expect(page.getByRole("button", { name: "Start a conversation" })).toBeVisible();
  await request.post(`http://127.0.0.1:${MOCK_PORT}/__revoke`);
  // The cookie is still there, so the page renders signed in; its first API call gets 401.
  await page.reload();
  await expect(page.locator(".sign-in__error")).toHaveText("Your session has ended. Sign in again.");
  expect((await context.cookies()).filter((item) => item.name === COOKIE)).toEqual([]);
});

// After every other test, so the log covers sign-in, streaming, errors and sign-out.
test("the Next server never logs the token, cookies or Authorization headers", () => {
  const log = readFileSync(SERVER_LOG, "utf8");
  expect(log.length).toBeGreaterThan(0);
  for (const secret of [E2E_TOKEN, E2E_PASSWORD, COOKIE, "Bearer ", "authorization", "cookie", "password"]) {
    expect(log.toLowerCase(), `server log contains ${secret}`).not.toContain(secret.toLowerCase());
  }
});
