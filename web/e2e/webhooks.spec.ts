import { randomUUID } from "node:crypto";

import { createCandidate, expect, test } from "./fixtures";

test("tenant admin registers a webhook, sees the delivery and redelivers it", async ({ actor }) => {
  const admin = await actor("admin");
  await admin.goto("/settings/webhooks");
  await admin.getByRole("button", { name: "New endpoint", exact: true }).click();
  const form = admin.getByRole("dialog", { name: "New webhook endpoint" });
  // The Compose webhook-demo sink answers 204 on its isolated, allowlisted bridge.
  await form.getByLabel("Receiver URL").fill(`http://webhook-demo:8080/events?run=${randomUUID()}`);
  await form.getByLabel("Description (optional)").fill("E2E redeliver flow");
  await form.getByLabel(/candidate_case\.created\.v1/).check();
  const created = admin.waitForResponse((res) => res.url().endsWith("/api/tf/v1/webhook-endpoints") && res.request().method() === "POST");
  await form.getByRole("button", { name: "Create endpoint", exact: true }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  expect(response.headers()["cache-control"]).toBe("no-store");
  const { id: endpointId } = (await response.json()) as { id: string };

  const reveal = admin.getByRole("dialog", { name: "Endpoint created" });
  await expect(reveal.getByLabel("Signing secret")).toHaveValue(/^whsec_/);
  await reveal.getByRole("button", { name: "I've stored the secret" }).click();
  await expect(reveal).toBeHidden();

  await createCandidate(admin);

  await admin.goto("/settings/webhooks");
  const endpoint = admin.locator(`li[data-endpoint-id="${endpointId}"]`);
  await endpoint.getByRole("button", { name: /^Deliveries for/ }).click();
  const log = admin.getByRole("region", { name: /^Delivery log:/ });
  const delivery = log.locator("tbody tr[data-delivery-id]").first();
  await expect(async () => {
    await log.getByRole("button", { name: "Refresh" }).click();
    await expect(delivery).toContainText("Succeeded", { timeout: 2_000 });
  }).toPass({ timeout: 60_000 });
  await expect(delivery).toContainText("candidate_case.created.v1");
  await expect(delivery).toContainText("HTTP 204");

  const redelivered = admin.waitForResponse((res) => res.url().endsWith("/redeliveries") && res.request().method() === "POST");
  await delivery.getByRole("button", { name: /^Redeliver candidate_case\.created\.v1/ }).click();
  expect((await redelivered).status()).toBe(202);
  await expect(log.getByRole("status").filter({ hasText: "Redelivery succeeded (HTTP 204)." })).toBeVisible({ timeout: 60_000 });

  await log.getByRole("button", { name: "Refresh" }).click();
  await expect(log.locator("tbody tr[data-delivery-id]")).toHaveCount(2);
  await expect(log.locator("tbody tr[data-delivery-id]").first()).toContainText("redelivery");

  await endpoint.getByRole("button", { name: /^Delete/ }).click();
  await admin.getByRole("dialog", { name: "Delete endpoint?" }).getByRole("button", { name: "Delete endpoint" }).click();
  await expect(endpoint).toBeHidden();
});

test("a recruiter cannot open the webhook screens or call the webhook API", async ({ actor }) => {
  const recruiter = await actor("recruiter");
  await expect(recruiter.getByRole("link", { name: "Webhooks" })).toHaveCount(0);
  await recruiter.goto("/settings/webhooks");
  await expect(recruiter.getByText("You don't have access")).toBeVisible();
  await expect(recruiter.getByRole("button", { name: "New endpoint" })).toHaveCount(0);
  const api = await recruiter.request.get("/api/tf/v1/webhook-endpoints");
  expect(api.status()).toBe(403);
});
