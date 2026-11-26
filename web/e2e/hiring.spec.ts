import { test, expect, createCandidate, moveCandidate } from "./fixtures";

test("recruiter hires a candidate after interview feedback and two approvals, with email in Mailpit", async ({ actor, request, page: mailbox }) => {
  const mailpit = process.env.E2E_MAILPIT_URL ?? `http://localhost:${process.env.MAILPIT_PORT ?? "8025"}`;
  type Message = { ID: string; Subject: string; To: { Address: string }[] };
  async function messages(): Promise<Message[]> {
    const response = await request.get(`${mailpit}/api/v1/messages`);
    expect(response.ok()).toBeTruthy();
    return (await response.json()).messages;
  }
  const baseline = new Set((await messages()).map((message) => message.ID));
  const recruiter = await actor("recruiter");
  const candidate = await createCandidate(recruiter);
  await moveCandidate(recruiter, candidate.name, "screening", "Screening");
  await recruiter.goto("/interviews");
  await recruiter.getByRole("button", { name: "Schedule interview", exact: true }).click();
  const schedule = recruiter.getByRole("dialog", { name: "Schedule interview" });
  await schedule.getByRole("combobox", { name: "Candidate", exact: true }).fill(candidate.name);
  await schedule.getByRole("listbox", { name: "Candidates", exact: true }).getByRole("option", { name: new RegExp(candidate.name) }).click();
  await schedule.getByLabel("Interviewer", { exact: true }).selectOption({ label: "interviewer@talentflow.local" });
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 16);
  await schedule.getByLabel("Date and time (your local time)").fill(tomorrow);
  await schedule.getByRole("button", { name: "Schedule", exact: true }).click();
  await expect(schedule).toBeHidden();
  await expect(recruiter.getByRole("region", { name: /^All interviews/ }).getByText(candidate.name, { exact: true })).toBeVisible();

  const interviewer = await actor("interviewer");
  await interviewer.getByRole("button", { name: `Give feedback for ${candidate.name}`, exact: true }).click();
  const feedback = interviewer.getByRole("dialog", { name: "Interview feedback" });
  await feedback.getByRole("radio", { name: "5 – Excellent", exact: true }).check();
  await feedback.getByRole("radio", { name: "Strong hire", exact: true }).check();
  await feedback.getByLabel("Comments").fill("Explained concurrency and tenant isolation clearly.");
  await feedback.getByRole("button", { name: "Submit feedback", exact: true }).click();
  await expect(feedback).toBeHidden();
  await interviewer.reload();
  const interview = interviewer.getByRole("listitem").filter({ hasText: candidate.name });
  await expect(interview).toContainText("Feedback submitted");
  await expect(interview.getByRole("button", { name: /Give feedback/ })).toHaveCount(0);

  await recruiter.goto(`/candidates?requisition=${candidate.requisition_id}`);
  await moveCandidate(recruiter, candidate.name, "interviewing", "Interviewing");
  await recruiter.goto("/offers");
  await recruiter.getByRole("button", { name: `Create offer for ${candidate.name}`, exact: true }).click();
  const offerForm = recruiter.getByRole("dialog", { name: "New offer" });
  await offerForm.getByLabel("Job title").fill(candidate.title);
  await offerForm.getByLabel("Annual salary").fill("90000");
  await offerForm.getByLabel("Currency").fill("EUR");
  await offerForm.getByRole("button", { name: "Create offer", exact: true }).click();
  const offer = recruiter.getByRole("dialog", { name: candidate.title, exact: true });
  await expect(offer).toContainText("Hiring manager (step 1)");
  await expect(offer.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  const offerId = new URL(recruiter.url()).searchParams.get("offer");
  expect(offerId).toBeTruthy();

  const manager = await actor("manager");
  await manager.goto(`/offers?offer=${offerId}`);
  const managerOffer = manager.getByRole("dialog", { name: candidate.title, exact: true });
  await managerOffer.getByLabel(/Reason/).fill("Interview evidence supports the offer.");
  await managerOffer.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(managerOffer).toContainText("Step 1: Approved");
  await expect(managerOffer).toContainText("Tenant admin (step 2)");
  await expect(managerOffer.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  await recruiter.goto(`/candidates?requisition=${candidate.requisition_id}`);
  await expect(recruiter.getByRole("region", { name: "Offer pending", exact: true }).getByText(candidate.name, { exact: true })).toBeVisible();
  await expect(recruiter.getByLabel(`Move ${candidate.name} to stage`).getByRole("option", { name: "Hired", exact: true })).toHaveCount(0);

  const admin = await actor("admin");
  await admin.goto(`/offers?offer=${offerId}`);
  const adminOffer = admin.getByRole("dialog", { name: candidate.title, exact: true });
  await adminOffer.getByLabel(/Reason/).fill("Budget approved.");
  await adminOffer.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(adminOffer).toContainText("Step 1: Approved");
  await expect(adminOffer).toContainText("Step 2: Approved");
  await expect(adminOffer.getByText("Approved", { exact: true })).toBeVisible();
  await recruiter.goto(`/candidates?requisition=${candidate.requisition_id}`);
  await moveCandidate(recruiter, candidate.name, "hired", "Hired");
  await recruiter.reload();
  await expect(recruiter.getByRole("region", { name: "Hired", exact: true }).getByText(candidate.name, { exact: true })).toBeVisible();

  // The worker delivers asynchronously. Check new mail for both approval actors,
  // without purging another run's inbox or accepting mail from an earlier run.
  for (const recipient of ["manager@talentflow.local", "admin@talentflow.local"]) {
    let delivered: Message | undefined;
    await expect.poll(async () => {
      delivered = (await messages()).find((message) => !baseline.has(message.ID)
        && message.Subject === "TalentFlow offer approval update"
        && message.To.some((to) => to.Address === recipient));
      return !!delivered;
    }, { timeout: 30_000, message: `Approval email delivered to ${recipient}` }).toBe(true);
    const detail = await request.get(`${mailpit}/api/v1/message/${delivered!.ID}`);
    expect(detail.ok()).toBeTruthy();
    expect((await detail.json()).Text).toContain("decision: approved");
  }
  await mailbox.goto(mailpit);
  await expect(mailbox.getByText("TalentFlow offer approval update", { exact: true }).first()).toBeVisible();
});

test("a stale candidate transition shows a conflict prompt and refreshes to the committed stage", async ({ actor }) => {
  const first = await actor("recruiter");
  const candidate = await createCandidate(first);
  const second = await actor("other-recruiter");
  await second.goto(`/candidates?requisition=${candidate.requisition_id}`);
  await moveCandidate(second, candidate.name, "screening", "Screening");

  const rejected = first.waitForResponse((response) => response.url().endsWith(`/${candidate.id}/stage`) && response.request().method() === "PATCH");
  await first.getByLabel(`Move ${candidate.name} to stage`, { exact: true }).selectOption("rejected");
  const conflictResponse = await rejected;
  expect(conflictResponse.request().postDataJSON()).toEqual({ target_stage: "rejected" });
  expect(await conflictResponse.request().headerValue("if-match")).toBe(`"${candidate.version}"`);
  expect(conflictResponse.status()).toBe(412);
  expect(conflictResponse.headers()["etag"]).toBe(`"${candidate.version + 1}"`);
  expect(conflictResponse.headers()["content-type"]).toContain("application/problem+json");
  const conflict = first.getByRole("alertdialog", { name: "Changed by someone else" });
  await expect(conflict).toContainText(`${candidate.name} was updated by someone else`);
  await expect(conflict).toContainText("Your move was not applied");
  await conflict.getByRole("button", { name: "Refresh board", exact: true }).click();
  await expect(conflict).toBeHidden();
  await expect(first.getByRole("region", { name: "Screening", exact: true }).getByText(candidate.name, { exact: true })).toBeVisible();
  await expect(first.getByRole("region", { name: "Rejected", exact: true }).getByText(candidate.name, { exact: true })).toHaveCount(0);
  await moveCandidate(first, candidate.name, "interviewing", "Interviewing");
});
