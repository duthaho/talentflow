// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";

import { fakeCandidate, fakeInterview, fakeInterviewsBackend } from "../../../test/interviews-fake";
import { InterviewsWorkspace, type InterviewPermissions } from "./interviews-workspace";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const INTERVIEWER: InterviewPermissions = { manage: false, submitFeedback: true, calendarSelf: true };
const RECRUITER: InterviewPermissions = { manage: true, submitFeedback: false, calendarSelf: false };

const INTERVIEWERS = [
  { id: "user-me", email: "interviewer@talentflow.local" },
  { id: "user-bo", email: "bo@talentflow.local" },
];

function section(id: string): HTMLElement {
  return document.querySelector<HTMLElement>(`section[data-section="${id}"]`)!;
}

async function settled() {
  await waitFor(() => expect(document.querySelectorAll('[aria-busy="true"]')).toHaveLength(0));
}

async function renderWorkspace(backend: ReturnType<typeof fakeInterviewsBackend>, permissions: InterviewPermissions) {
  render(<InterviewsWorkspace api={backend.api} permissions={permissions} />);
  await settled();
}

function posts(backend: ReturnType<typeof fakeInterviewsBackend>, fragment: string) {
  return backend.requests.filter((request) => request.method === "POST" && request.url.includes(fragment));
}

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
  vi.mocked(toast.success).mockClear();
});

describe("InterviewsWorkspace for an interviewer", () => {
  it("lists only their own interviews and hides recruiter actions", async () => {
    const backend = fakeInterviewsBackend({
      interviews: [
        fakeInterview("i1"),
        fakeInterview("i2", { feedback_submitted: true, scheduled_at: "2026-11-20T09:00:00Z" }),
        fakeInterview("i3", { interviewer_id: "user-bo" }),
      ],
    });
    await renderWorkspace(backend, { ...INTERVIEWER, calendarSelf: false });

    const mine = section("my-interviews");
    const rows = within(mine).getAllByRole("listitem");
    expect(rows.map((row) => row.dataset.interviewId)).toEqual(["i2", "i1"]);
    expect(within(mine).getByText("1 waiting for your feedback.")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Feedback submitted")).toBeInTheDocument();
    expect(within(rows[0]).queryByRole("button")).not.toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "Give feedback for Ada i1" })).toBeInTheDocument();
    expect(within(rows[1]).getByText("Backend Engineer")).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /Schedule interview/ })).not.toBeInTheDocument();
    expect(section("all-interviews")).toBeNull();
    expect(section("calendar-links")).toBeNull();
    const query = new URL(backend.requests[0].url).searchParams;
    expect(query.get("interviewer")).toBe("me");
    expect(query.get("limit")).toBe("25");
    expect(backend.requests.some((request) => request.url.includes("/v1/interviewers"))).toBe(false);
  });

  it("shows an empty state when nothing is assigned", async () => {
    await renderWorkspace(fakeInterviewsBackend({}), { ...INTERVIEWER, calendarSelf: false });
    expect(within(section("my-interviews")).getByText(/No interviews are assigned to you/)).toBeInTheDocument();
  });

  it("shows a load error with a working retry", async () => {
    let fail = true;
    const backend = fakeInterviewsBackend({
      interviews: [fakeInterview("i1")],
      override: () => (fail ? Response.json({ type: `${PROBLEM_TYPE_BASE}unavailable`, title: "Service unavailable", status: 503 }, { status: 503 }) : undefined),
    });
    await renderWorkspace(backend, { ...INTERVIEWER, calendarSelf: false });

    const alert = within(section("my-interviews")).getByRole("alert");
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await settled();
    expect(within(section("my-interviews")).getByText("Ada i1")).toBeInTheDocument();
  });

  it("validates feedback, submits it once and locks the interview", async () => {
    const backend = fakeInterviewsBackend({ interviews: [fakeInterview("i1")] });
    await renderWorkspace(backend, { ...INTERVIEWER, calendarSelf: false });

    await userEvent.click(screen.getByRole("button", { name: "Give feedback for Ada i1" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Ada i1 · Backend Engineer/)).toBeInTheDocument();
    expect(within(dialog).getByText(/You can submit feedback once/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Submit feedback" }));
    expect(within(dialog).getByText("Choose a score from 1 to 5.")).toBeInTheDocument();
    expect(within(dialog).getByText("Choose a recommendation.")).toBeInTheDocument();
    expect(within(dialog).getByText("Write a short justification for your score.")).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: "1 – Poor" })).toHaveFocus();
    expect(posts(backend, "/feedback")).toHaveLength(0);

    await userEvent.click(within(dialog).getByRole("radio", { name: "4 – Good" }));
    await userEvent.click(within(dialog).getByRole("radio", { name: "Hire" }));
    // The fixture tests validation and submission; per-character keyboard events
    // needlessly consume the wall-clock budget on shared runners.
    await userEvent.click(within(dialog).getByLabelText("Comments"));
    await userEvent.paste("  Clear trade-offs in the design round.  ");
    expect(within(dialog).getByText("41/5000")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit feedback" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const sent = posts(backend, "/v1/interviews/i1/feedback");
    expect(sent).toHaveLength(1);
    expect(await sent[0].json()).toEqual({ score: 4, recommendation: "hire", comments: "Clear trade-offs in the design round." });
    expect(toast.success).toHaveBeenCalledWith("Feedback for Ada i1 submitted.");

    const row = within(section("my-interviews")).getByRole("listitem");
    expect(within(row).getByText("Feedback submitted")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /Give feedback/ })).not.toBeInTheDocument();
    expect(within(section("my-interviews")).getByText("0 waiting for your feedback.")).toBeInTheDocument();
  });

  it("explains a 409 when feedback was already submitted elsewhere", async () => {
    const backend = fakeInterviewsBackend({ interviews: [fakeInterview("i1")] });
    await renderWorkspace(backend, { ...INTERVIEWER, calendarSelf: false });
    backend.store.get("i1")!.feedback_submitted = true;

    await userEvent.click(screen.getByRole("button", { name: "Give feedback for Ada i1" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("radio", { name: "2 – Weak" }));
    await userEvent.click(within(dialog).getByRole("radio", { name: "No hire" }));
    await userEvent.click(within(dialog).getByLabelText("Comments"));
    await userEvent.paste("Struggled with basics.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit feedback" }));

    expect(await within(dialog).findByRole("status")).toHaveTextContent("Feedback for this interview was already submitted.");
    expect(within(dialog).queryByRole("button", { name: "Submit feedback" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Got it" }));
    expect(within(section("my-interviews")).getByText("Feedback submitted")).toBeInTheDocument();
  });

  it("shows the API problem when the interviewer is not assigned", async () => {
    const backend = fakeInterviewsBackend({
      interviews: [fakeInterview("i1")],
      override: (request) =>
        request.method === "POST"
          ? Response.json({ type: `${PROBLEM_TYPE_BASE}forbidden`, title: "Forbidden", status: 403, detail: "Only the assigned interviewer can submit feedback" }, { status: 403 })
          : undefined,
    });
    await renderWorkspace(backend, { ...INTERVIEWER, calendarSelf: false });

    await userEvent.click(screen.getByRole("button", { name: "Give feedback for Ada i1" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("radio", { name: "5 – Excellent" }));
    await userEvent.click(within(dialog).getByRole("radio", { name: "Strong hire" }));
    await userEvent.click(within(dialog).getByLabelText("Comments"));
    await userEvent.paste("Great.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit feedback" }));

    expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Submit feedback" })).toBeInTheDocument();
    expect(within(section("my-interviews")).getByText("Feedback pending")).toBeInTheDocument();
  });
});

describe("InterviewsWorkspace for a recruiter", () => {
  it("schedules an interview with a chosen candidate and interviewer", async () => {
    const backend = fakeInterviewsBackend({
      canManage: true,
      interviewers: INTERVIEWERS,
      candidates: [fakeCandidate("c1", "screening"), fakeCandidate("c2", "interviewing"), fakeCandidate("c3", "applied")],
    });
    await renderWorkspace(backend, RECRUITER);
    expect(section("my-interviews")).toBeNull();
    expect(within(section("all-interviews")).getByText("No interviews scheduled yet.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Schedule interview" }));
    const dialog = screen.getByRole("dialog");
    const candidates = await within(dialog).findByRole("listbox", { name: "Candidates" });
    expect(within(candidates).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Grace c1c1@x.test · Screening",
      "Grace c2c2@x.test · Interviewing",
    ]);
    const stages = backend.requests.filter((request) => request.url.includes("/v1/candidate-cases")).map((request) => new URL(request.url).searchParams.get("stage"));
    expect(stages).toEqual(["screening", "interviewing"]);

    await userEvent.click(within(candidates).getByRole("option", { name: /Grace c2/ }));
    await userEvent.selectOptions(within(dialog).getByLabelText("Interviewer"), "user-bo");
    fireEvent.change(within(dialog).getByLabelText(/Date and time/), { target: { value: "2026-12-03T14:00" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Schedule" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await posts(backend, "/v1/candidate-cases/c2/interviews")[0].json()).toEqual({
      interviewer_id: "user-bo",
      scheduled_at: new Date(2026, 11, 3, 14, 0).toISOString(),
    });
    expect(toast.success).toHaveBeenCalledWith("Interview scheduled for Grace c2 with bo@talentflow.local.");
    await settled();
    const row = within(section("all-interviews")).getByRole("listitem");
    expect(within(row).getByText("Grace c2")).toBeInTheDocument();
    expect(within(row).getByText(/bo@talentflow\.local/)).toBeInTheDocument();
    expect(within(row).getByText("Feedback pending")).toBeInTheDocument();
  });

  it("keeps the dialog open with the API problem when scheduling fails", async () => {
    const backend = fakeInterviewsBackend({
      canManage: true,
      interviewers: INTERVIEWERS,
      candidates: [fakeCandidate("c1")],
      override: (request) =>
        request.method === "POST"
          ? Response.json({ type: `${PROBLEM_TYPE_BASE}not-found`, title: "Not found", status: 404, detail: "Candidate case or interviewer not found" }, { status: 404 })
          : undefined,
    });
    await renderWorkspace(backend, RECRUITER);

    await userEvent.click(screen.getByRole("button", { name: "Schedule interview" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("option", { name: /Grace c1/ }));
    await userEvent.selectOptions(within(dialog).getByLabelText("Interviewer"), "user-me");
    fireEvent.change(within(dialog).getByLabelText(/Date and time/), { target: { value: "2026-12-03T14:00" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Schedule" }));

    expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("requires a candidate and clears the search on Escape without closing the dialog", async () => {
    const backend = fakeInterviewsBackend({ canManage: true, interviewers: INTERVIEWERS, candidates: [fakeCandidate("c1")] });
    await renderWorkspace(backend, RECRUITER);

    await userEvent.click(screen.getByRole("button", { name: "Schedule interview" }));
    const dialog = screen.getByRole("dialog");
    const search = await within(dialog).findByRole("combobox", { name: "Candidate" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Interviewer"), "user-me");
    fireEvent.change(within(dialog).getByLabelText(/Date and time/), { target: { value: "2026-12-03T14:00" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Schedule" }));
    expect(within(dialog).getByText("Choose a candidate.")).toBeInTheDocument();
    expect(posts(backend, "/interviews")).toHaveLength(0);

    await userEvent.type(search, "zz");
    await userEvent.keyboard("{Escape}");
    expect(search).toHaveValue("");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("explains why scheduling is impossible without interviewers", async () => {
    const backend = fakeInterviewsBackend({ canManage: true, candidates: [fakeCandidate("c1")] });
    await renderWorkspace(backend, RECRUITER);

    await userEvent.click(screen.getByRole("button", { name: "Schedule interview" }));
    expect(await within(screen.getByRole("dialog")).findByText(/no members with the Interviewer role/)).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).queryByRole("button", { name: "Schedule" })).not.toBeInTheDocument();
  });

  it("filters all interviews by interviewer", async () => {
    const backend = fakeInterviewsBackend({
      canManage: true,
      actorId: "user-recruiter",
      interviewers: INTERVIEWERS,
      interviews: [fakeInterview("i1"), fakeInterview("i2", { interviewer_id: "user-bo", interviewer_email: "bo@talentflow.local" })],
    });
    await renderWorkspace(backend, RECRUITER);
    expect(within(section("all-interviews")).getAllByRole("listitem")).toHaveLength(2);

    const filter = screen.getByLabelText("Interviewer");
    await waitFor(() => expect(within(filter).getAllByRole("option")).toHaveLength(3));
    await userEvent.selectOptions(filter, "user-bo");
    await settled();

    const rows = within(section("all-interviews")).getAllByRole("listitem");
    expect(rows.map((row) => row.dataset.interviewId)).toEqual(["i2"]);
    expect(new URL(backend.requests.at(-1)!.url).searchParams.get("interviewer")).toBe("user-bo");
  });
});
