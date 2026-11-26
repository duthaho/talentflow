import { randomUUID } from "node:crypto";
import { test as base, expect, type BrowserContext, type Page } from "@playwright/test";

type Actor = "recruiter" | "interviewer" | "manager" | "admin" | "other-recruiter";

// Separate OIDC sessions are essential: a role must never inherit another role's cookies.
// These contexts are lazy so the conflict scenario only starts the two actors it uses.
export const test = base.extend<{ actor: (role: Actor) => Promise<Page> }>({
  actor: async ({ browser, baseURL, contextOptions }, provide) => {
    const actors = new Map<Actor, { context: BrowserContext; page: Page }>();
    try {
      await provide(async (role) => {
        const existing = actors.get(role);
        if (existing) return existing.page;
        const context = await browser.newContext({ ...contextOptions, baseURL, timezoneId: "UTC", viewport: { width: 1440, height: 1000 } });
        const page = await context.newPage();
        actors.set(role, { context, page });
        const username = role === "other-recruiter" ? "recruiter" : role;
        await page.goto("/auth/login?returnTo=/interviews");
        await page.getByLabel("Username or email").fill(`${username}@talentflow.local`);
        await page.getByLabel("Password", { exact: true }).fill(process.env.DEMO_USER_PASSWORD ?? "dev-demo-password");
        await page.getByRole("button", { name: "Sign In", exact: true }).click();
        await expect(page).toHaveURL(`${baseURL}/interviews`);
        return page;
      });
    } finally {
      // Playwright's runner records every new context and captures screenshots
      // before it closes, including contexts created outside the page fixture.
      for (const { context } of actors.values()) await context.close();
    }
  },
});

export { expect };

export async function createCandidate(page: Page) {
  const suffix = randomUUID().slice(0, 8);
  const title = `E2E engineer ${suffix}`;
  const name = `E2E Candidate${suffix}`;
  await page.goto("/candidates");
  await page.getByRole("button", { name: "New requisition", exact: true }).click();
  const requisition = page.getByRole("dialog", { name: "New requisition" });
  await requisition.getByLabel("Title", { exact: true }).fill(title);
  await requisition.getByLabel("Department").fill("E2E Engineering");
  await requisition.getByRole("button", { name: "Create requisition", exact: true }).click();
  await expect(requisition).toBeHidden();
  await expect(page.getByLabel("Requisition", { exact: true })).toContainText(title);
  await page.getByRole("button", { name: "New candidate", exact: true }).click();
  const candidate = page.getByRole("dialog", { name: "New candidate" });
  await candidate.getByLabel("First name").fill("E2E");
  await candidate.getByLabel("Last name").fill(`Candidate${suffix}`);
  await candidate.getByLabel("Email", { exact: true }).fill(`e2e-${suffix}@example.test`);
  const created = page.waitForResponse((response) => response.url().endsWith("/api/tf/v1/candidate-cases") && response.request().method() === "POST");
  await candidate.getByRole("button", { name: "Create candidate", exact: true }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const record = await response.json() as { id: string; version: number; requisition_id: string };
  await expect(candidate).toBeHidden();
  await expect(page.getByRole("region", { name: "Applied", exact: true }).getByText(name, { exact: true })).toBeVisible();
  return { ...record, name, title };
}

export async function moveCandidate(page: Page, name: string, stage: string, label: string) {
  const response = page.waitForResponse((res) => res.url().endsWith("/stage") && res.request().method() === "PATCH");
  await page.getByLabel(`Move ${name} to stage`, { exact: true }).selectOption(stage);
  const moved = await response;
  expect(moved.status()).toBe(200);
  await expect(page.getByRole("region", { name: label, exact: true }).getByText(name, { exact: true })).toBeVisible();
  return moved;
}
