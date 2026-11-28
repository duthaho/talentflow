import { execFileSync } from "node:child_process";
import { readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "./fixtures";
import type { Page } from "@playwright/test";

// The real flagd container reads this bind-mounted file (docker-compose.yml) and hot-reloads it.
const REPO = path.resolve(process.cwd(), "..");
const FLAG_FILE = path.join(REPO, "flags", "talentflow.flagd.json");
const SEED_TENANT = "00000000-0000-4000-8000-000000000001";
const NOTICE = /Webhooks are turned off for your organization/;

type FlagFile = { flags: Record<string, { targeting?: { if: [{ in: [unknown, string[]] }, string, null] } }> };

const original = readFileSync(FLAG_FILE, "utf8");

function writeFlags(edit: (file: FlagFile) => void) {
  const file = JSON.parse(original) as FlagFile;
  edit(file);
  // Write-then-rename is how editors save, and it is what flagd's file watch must pick up.
  const staging = `${FLAG_FILE}.e2e`;
  writeFileSync(staging, `${JSON.stringify(file, null, 2)}\n`);
  renameSync(staging, FLAG_FILE);
}

function restoreFlags() {
  const staging = `${FLAG_FILE}.e2e`;
  writeFileSync(staging, original);
  renameSync(staging, FLAG_FILE);
}

function compose(...args: string[]) {
  execFileSync("docker", ["compose", ...args], { cwd: REPO, stdio: "inherit" });
}

async function webhooksFeature(page: Page) {
  const response = await page.request.get("/api/tf/v1/me");
  expect(response.status()).toBe(200);
  return ((await response.json()) as { features: { webhooks: { enabled: boolean; delivery_paused: boolean } } }).features.webhooks;
}

// ADR-010 §4: the API enforces a saved file change within 5 s; the web shows it on the next server render.
async function expectFeature(page: Page, expected: { enabled: boolean; delivery_paused: boolean }, timeout = 5_000) {
  await expect.poll(() => webhooksFeature(page), { timeout, intervals: [250] }).toEqual(expected);
}

test.describe.configure({ mode: "serial" });

test.afterEach(() => restoreFlags());

test("toggling the release gate in the flag file switches the admin's webhook screens without a redeploy", async ({ actor }) => {
  const admin = await actor("admin");
  await expectFeature(admin, { enabled: true, delivery_paused: false });
  await admin.goto("/settings/webhooks");
  await expect(admin.getByRole("link", { name: "Webhooks" })).toBeVisible();
  await admin.getByRole("button", { name: "New endpoint", exact: true }).click();
  const form = admin.getByRole("dialog", { name: "New webhook endpoint" });
  await form.getByLabel("Receiver URL").fill("http://webhook-demo:8080/events?run=gate-closed");
  await form.getByLabel(/candidate_case\.created\.v1/).check();

  writeFlags((file) => {
    file.flags["release.webhooks.outbound"].targeting!.if[0].in[1] = [];
  });
  // ADR-010 §1: delivery needs both flags, so a closed gate also reports delivery as paused.
  await expectFeature(admin, { enabled: false, delivery_paused: true });

  // The gate closed while the form was open: the 403 swaps the form for the notice and re-renders the shell.
  const refused = admin.waitForResponse((res) => res.url().endsWith("/api/tf/v1/webhook-endpoints") && res.request().method() === "POST");
  await form.getByRole("button", { name: "Create endpoint", exact: true }).click();
  const response = await refused;
  expect(response.status()).toBe(403);
  expect(await response.json()).toMatchObject({ type: expect.stringMatching(/#feature-disabled$/), feature: "webhooks" });
  await expect(form).toBeHidden();
  await expect(admin.getByRole("status").filter({ hasText: NOTICE })).toBeVisible();
  await expect(admin.getByRole("link", { name: "Webhooks" })).toHaveCount(0);
  await expect(admin.getByRole("button", { name: "New endpoint" })).toHaveCount(0);
  await admin.screenshot({ path: "test-results/feature-flags-gate-off.png", fullPage: true });

  restoreFlags();
  await expectFeature(admin, { enabled: true, delivery_paused: false });
  await admin.reload();
  await expect(admin.getByRole("link", { name: "Webhooks" })).toBeVisible();
  await expect(admin.getByRole("button", { name: "New endpoint", exact: true })).toBeVisible();
  await expect(admin.getByText(NOTICE)).toHaveCount(0);
});

test("the delivery kill switch shows the paused banner and keeps management available", async ({ actor }) => {
  const admin = await actor("admin");
  writeFlags((file) => {
    file.flags["ops.webhooks.delivery"].targeting!.if[0].in[1] = [SEED_TENANT];
  });
  await expectFeature(admin, { enabled: true, delivery_paused: true });
  await admin.goto("/settings/webhooks");
  await expect(admin.getByRole("status").filter({ hasText: "Delivery is paused for your organization." })).toBeVisible();
  await expect(admin.getByRole("button", { name: "New endpoint", exact: true })).toBeEnabled();
  await admin.screenshot({ path: "test-results/feature-flags-delivery-paused.png", fullPage: true });
});

test("a flagd outage falls back to gate off and delivery paused, and the web recovers with flagd", async ({ actor }) => {
  const admin = await actor("admin");
  await expectFeature(admin, { enabled: true, delivery_paused: false });
  compose("stop", "flagd");
  try {
    await expectFeature(admin, { enabled: false, delivery_paused: true });
    await admin.goto("/settings/webhooks");
    await expect(admin.getByRole("status").filter({ hasText: NOTICE })).toBeVisible();
    await expect(admin.getByText(/Delivery is paused/)).toHaveCount(0);
    await expect(admin.getByRole("link", { name: "Webhooks" })).toHaveCount(0);
    const endpoints = await admin.request.get("/api/tf/v1/webhook-endpoints");
    expect(endpoints.status(), "reads keep working while flagd is down").toBe(200);
    await admin.screenshot({ path: "test-results/feature-flags-flagd-outage.png", fullPage: true });
  } finally {
    compose("start", "flagd");
  }
  await expectFeature(admin, { enabled: true, delivery_paused: false }, 30_000);
  await admin.reload();
  await expect(admin.getByRole("button", { name: "New endpoint", exact: true })).toBeVisible();
});
