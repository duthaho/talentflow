import { randomUUID } from "node:crypto";
import { test, expect } from "./fixtures";

test("publish, apply anonymously with a scanned CV, and inspect immutable consent as staff", async ({
  actor,
  browser,
  baseURL,
}) => {
  const recruiter = await actor("recruiter");
  const suffix = randomUUID().slice(0, 8);
  const title = `Careers engineer ${suffix}`;
  const created = await recruiter.request.post("/api/tf/v1/requisitions", {
    headers: { origin: baseURL! },
    data: { title, department: "Careers Engineering" },
  });
  expect(created.status()).toBe(201);
  const job = await created.json();
  const published = await recruiter.request.patch(
    `/api/tf/v1/requisitions/${job.id}/publication`,
    { headers: { origin: baseURL! }, data: { published: true } },
  );
  expect(published.status()).toBe(200);
  const anonymous = await browser.newContext({ baseURL });
  try {
    const applicant = await anonymous.newPage();
    await applicant.goto("/careers/talentflow-demo");
    await applicant.getByRole("link", { name: title, exact: true }).click();
    const consent = await applicant
      .getByRole("region", { name: "Application consent" })
      .locator("p")
      .innerText();
    await applicant.getByLabel("First name", { exact: true }).fill("Careers");
    await applicant
      .getByLabel("Last name", { exact: true })
      .fill(`Applicant${suffix}`);
    await applicant
      .getByLabel("Email", { exact: true })
      .fill(`careers-${suffix}@example.test`);
    await applicant.getByLabel(/CV \(PDF/).setInputFiles({
      name: "resume.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.7\nClean careers CV\n%%EOF"),
    });
    await applicant.getByRole("checkbox").check();
    const accepted = applicant.waitForResponse(
      (response) =>
        response.url().includes("/api/public/careers/") &&
        response.request().method() === "POST",
    );
    await applicant.getByRole("button", { name: "Send application" }).click();
    expect((await accepted).status()).toBe(202);
    await expect(
      applicant.getByRole("heading", { name: "Application received" }),
    ).toBeVisible();
    expect(await anonymous.cookies()).toEqual([]);
    const cases = await recruiter.request.get(
      `/api/tf/v1/candidate-cases?q=${encodeURIComponent(`careers-${suffix}`)}`,
    );
    expect(cases.status()).toBe(200);
    const candidate = (await cases.json()).items[0];
    await recruiter.goto(`/candidates/${candidate.id}`);
    await expect(recruiter.getByText("Source: careers page")).toBeVisible();
    const panel = recruiter.getByRole("region", {
      name: "Consent",
      exact: true,
    });
    await expect(panel).toContainText("careers-v1");
    await expect(panel).toContainText(consent);
    await expect(
      recruiter.getByText("resume.pdf", { exact: true }),
    ).toBeVisible();
  } finally {
    await anonymous.close();
  }
});

test("unknown careers slug returns a 404 without requiring a session", async ({
  page,
}) => {
  const response = await page.goto(`/careers/missing-${randomUUID()}`);
  expect(response?.status()).toBe(404);
  await expect(page.getByText("This page could not be found.")).toBeVisible();
});
