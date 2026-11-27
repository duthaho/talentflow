// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";

import { candidateCase, fakeOffer, fakeOffersBackend, type FakeOffer } from "../../../test/offers-fake";
import { OffersWorkspace } from "./offers-workspace";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const STEP_1 = fakeOffer("o1");
const STEP_2 = fakeOffer("o2", {
  approval_step: 2,
  version: 2,
  decisions: [{ step: 1, decision: "approved", actor_id: "user-hm-12345", decided_at: "2026-11-26T09:00:00Z", reason: null }],
});
const REJECTED = fakeOffer("o3", {
  status: "rejected",
  version: 2,
  decisions: [{ step: 1, decision: "rejected", actor_id: "user-hm-12345", decided_at: null, reason: "Above band" }],
});

function section(id: string): HTMLElement {
  return document.querySelector<HTMLElement>(`section[data-section="${id}"]`)!;
}

function sheet(): HTMLElement {
  return screen.getByRole("dialog");
}

async function settled() {
  await waitFor(() => expect(document.querySelectorAll('[aria-busy="true"]')).toHaveLength(0));
}

async function renderWorkspace(backend: ReturnType<typeof fakeOffersBackend>, { canCreate = false, initialOfferId = null as string | null } = {}) {
  render(<OffersWorkspace api={backend.api} currentUserId="user-me" canCreate={canCreate} initialOfferId={initialOfferId} />);
  await settled();
}

async function openOffer(title: string, within_ = section("offers-all")) {
  await userEvent.click(within(within_).getByRole("button", { name: new RegExp(title) }));
  await waitFor(() => expect(within(sheet()).getByRole("heading", { name: title })).toBeInTheDocument());
  await settled();
}

function posts(backend: ReturnType<typeof fakeOffersBackend>) {
  return backend.requests.filter((request) => request.method === "POST");
}

// Form fixtures exercise validation and payloads without a timer per keystroke.
async function pasteInto(field: HTMLElement, text: string) {
  await userEvent.click(field);
  await userEvent.paste(text);
}

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
  vi.mocked(toast.success).mockClear();
  window.history.replaceState(null, "", "/offers");
});

describe("OffersWorkspace", () => {
  it("shows a hiring manager only the offers waiting on their step", async () => {
    const backend = fakeOffersBackend({ role: "hiring_manager", offers: [STEP_1, STEP_2, REJECTED] });
    await renderWorkspace(backend);

    const inbox = section("offers-inbox");
    expect(within(inbox).getByRole("button", { name: /Engineer o1/ })).toBeInTheDocument();
    expect(within(inbox).queryByText("Engineer o2")).not.toBeInTheDocument();
    expect(within(inbox).getByLabelText("1 total")).toBeInTheDocument();
    expect(within(section("offers-all")).getAllByRole("listitem")).toHaveLength(3);
    expect(await within(inbox).findByText("Ada case-o1")).toBeInTheDocument();
    expect(section("offers-ready")).toBeNull();

    const inboxQuery = new URL(backend.requests.find((request) => request.url.includes("awaiting"))!.url).searchParams;
    expect(inboxQuery.get("awaiting")).toBe("me");
    expect(inboxQuery.get("limit")).toBe("25");
  });

  it("approves without a reason and moves the offer out of the inbox", async () => {
    const backend = fakeOffersBackend({ role: "hiring_manager", offers: [STEP_1] });
    await renderWorkspace(backend);
    await openOffer("Engineer o1", section("offers-inbox"));
    expect(window.location.search).toBe("?offer=o1");

    await userEvent.click(within(sheet()).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(within(sheet()).getByText("Step 1: Approved")).toBeInTheDocument());

    expect(posts(backend)[0].headers.get("if-match")).toBe('"1"');
    expect(await posts(backend)[0].json()).toEqual({ decision: "approved", reason: null });
    expect(within(sheet()).getByText("by You")).toBeInTheDocument();
    expect(within(sheet()).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(within(sheet()).getByText(/Only a tenant admin can decide this step/)).toBeInTheDocument();
    await settled();
    expect(within(section("offers-inbox")).getByText(/Nothing is waiting on you/)).toBeInTheDocument();
  });

  it("requires a reason to reject and sends it trimmed", async () => {
    const backend = fakeOffersBackend({ role: "tenant_admin", offers: [STEP_2] });
    await renderWorkspace(backend);
    await openOffer("Engineer o2", section("offers-inbox"));

    const reject = within(sheet()).getByRole("button", { name: "Reject" });
    await pasteInto(within(sheet()).getByLabelText(/Reason/), "   ");
    await userEvent.click(reject);
    expect(within(sheet()).getByRole("alert")).toHaveTextContent("Give a reason for the rejection.");
    expect(within(sheet()).getByLabelText(/Reason/)).toHaveFocus();
    expect(posts(backend)).toHaveLength(0);

    await pasteInto(within(sheet()).getByLabelText(/Reason/), "Above band for level  ");
    await userEvent.click(reject);
    await waitFor(() => expect(within(sheet()).getByText("Step 2: Rejected")).toBeInTheDocument());
    expect(posts(backend)[0].headers.get("if-match")).toBe('"2"');
    expect(await posts(backend)[0].json()).toEqual({ decision: "rejected", reason: "Above band for level" });
    expect(within(sheet()).getByText("Above band for level")).toBeInTheDocument();
  });

  it("blocks a reason over 500 characters before calling the API", async () => {
    const backend = fakeOffersBackend({ role: "hiring_manager", offers: [STEP_1] });
    await renderWorkspace(backend);
    await openOffer("Engineer o1", section("offers-inbox"));

    const reason = within(sheet()).getByLabelText(/Reason/);
    await userEvent.click(reason);
    await userEvent.paste("x".repeat(501));
    expect(within(sheet()).getByText("501/500")).toBeInTheDocument();
    await userEvent.click(within(sheet()).getByRole("button", { name: "Approve" }));
    expect(within(sheet()).getByRole("alert")).toHaveTextContent("500 characters or fewer");
    expect(posts(backend)).toHaveLength(0);
  });

  it("renders decision history in step order, reasons as plain text and legacy timestamps as a dash", async () => {
    const markup = '<img src=x onerror="alert(1)"> **bold**';
    const backend = fakeOffersBackend({
      role: "auditor",
      offers: [
        fakeOffer("o4", {
          status: "rejected",
          approval_step: 2,
          version: 3,
          decisions: [
            { step: 1, decision: "approved", actor_id: "user-hm-12345", decided_at: null, reason: null },
            { step: 2, decision: "rejected", actor_id: "user-me", decided_at: "2026-11-26T10:30:00Z", reason: markup },
          ],
        }),
      ],
    });
    await renderWorkspace(backend);
    await openOffer("Engineer o4");

    const steps = within(sheet()).getAllByRole("listitem");
    expect(steps.map((item) => item.dataset.step)).toEqual(["1", "2"]);
    expect(within(steps[0]).getByText("—")).toBeInTheDocument();
    expect(within(steps[0]).getByText("by User user-hm-")).toBeInTheDocument();
    expect(within(steps[1]).getByText("Nov 26, 2026, 10:30 AM UTC")).toBeInTheDocument();
    expect(within(steps[1]).getByText(markup)).toBeInTheDocument();
    expect(sheet().querySelector("img")).toBeNull();
    expect(within(sheet()).queryByRole("button", { name: /Approve|Reject/ })).not.toBeInTheDocument();
  });

  it("hides decision actions when the API says the caller cannot decide", async () => {
    const backend = fakeOffersBackend({ role: "recruiter", offers: [STEP_1] });
    await renderWorkspace(backend);

    expect(within(section("offers-inbox")).getByText(/Nothing is waiting on you/)).toBeInTheDocument();
    await openOffer("Engineer o1");
    expect(within(sheet()).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(within(sheet()).getByText(/Only a hiring manager can decide this step/)).toBeInTheDocument();
  });

  it.each([
    [412, "precondition-failed"],
    [409, "version-conflict"],
  ])("refreshes and explains when another approver decided first (%i)", async (status, slug) => {
    let conflictOnce = true;
    const backend = fakeOffersBackend({
      role: "hiring_manager",
      offers: [STEP_1],
      override: (request) => {
        if (request.method !== "POST" || !conflictOnce) return undefined;
        conflictOnce = false;
        const offer = backend.store.get("o1")!;
        offer.status = "rejected";
        offer.version = 2;
        offer.decisions.push({ step: 1, decision: "rejected", actor_id: "user-other-1", decided_at: "2026-11-26T09:00:00Z", reason: "No budget" });
        return Response.json(
          { type: `${PROBLEM_TYPE_BASE}${slug}`, title: "Conflict", status, current_version: 2 },
          { status, headers: { etag: '"2"' } },
        );
      },
    });
    await renderWorkspace(backend);
    await openOffer("Engineer o1", section("offers-inbox"));

    await userEvent.click(within(sheet()).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(within(sheet()).getByText("Changed by someone else")).toBeInTheDocument());
    expect(within(sheet()).getByText("No budget")).toBeInTheDocument();
    expect(within(sheet()).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(posts(backend)).toHaveLength(1);
  });

  it("shows the API's refusal and reloads when the role check fails server-side", async () => {
    const backend = fakeOffersBackend({
      role: "hiring_manager",
      offers: [STEP_1],
      override: (request) =>
        request.method === "POST"
          ? Response.json({ type: `${PROBLEM_TYPE_BASE}forbidden`, title: "Forbidden", status: 403, detail: "Actor cannot approve this step" }, { status: 403 })
          : undefined,
    });
    await renderWorkspace(backend);
    await openOffer("Engineer o1", section("offers-inbox"));

    const detailsBefore = backend.requests.filter((request) => request.url.endsWith("/v1/offers/o1")).length;
    await userEvent.click(within(sheet()).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("You don't have access", expect.anything()));
    await settled();
    expect(backend.requests.filter((request) => request.url.endsWith("/v1/offers/o1")).length).toBe(detailsBefore + 1);
  });

  it("lets a recruiter create an offer for an interviewing candidate", async () => {
    const backend = fakeOffersBackend({ role: "recruiter", candidates: [candidateCase("c1"), candidateCase("c2", "screening")] });
    await renderWorkspace(backend, { canCreate: true });

    const ready = section("offers-ready");
    expect(within(ready).getAllByRole("listitem")).toHaveLength(1);
    await userEvent.click(within(ready).getByRole("button", { name: "Create offer for Ada c1" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/For Ada c1/)).toBeInTheDocument();
    await pasteInto(within(dialog).getByLabelText("Job title"), "Staff Engineer");
    await pasteInto(within(dialog).getByLabelText("Annual salary"), "130000");
    await userEvent.clear(within(dialog).getByLabelText("Currency"));
    await pasteInto(within(dialog).getByLabelText("Currency"), "usd");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create offer" }));

    await waitFor(() => expect(within(sheet()).getByRole("heading", { name: "Staff Engineer" })).toBeInTheDocument());
    const create = posts(backend)[0];
    expect(new URL(create.url).pathname).toBe("/v1/candidate-cases/c1/offers");
    expect(await create.json()).toEqual({ title: "Staff Engineer", annual_salary: 130000, currency: "USD" });
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Offer created for Ada c1"));
    expect(within(ready).getByText("No candidates are in the Interviewing stage.")).toBeInTheDocument();
    await settled();
    expect(within(sheet()).getByText("$130,000")).toBeInTheDocument();
    expect(within(section("offers-all")).getByText("Ada c1")).toBeInTheDocument();
  });

  it("keeps the dialog open with the API's reason when creation is refused", async () => {
    const backend = fakeOffersBackend({
      role: "recruiter",
      candidates: [candidateCase("c1")],
      override: (request) =>
        request.method === "POST"
          ? Response.json({ type: `${PROBLEM_TYPE_BASE}conflict`, title: "Conflict", status: 409, detail: "Offer already exists" }, { status: 409 })
          : undefined,
    });
    await renderWorkspace(backend, { canCreate: true });

    await userEvent.click(within(section("offers-ready")).getByRole("button", { name: "Create offer for Ada c1" }));
    const dialog = screen.getByRole("dialog");
    await pasteInto(within(dialog).getByLabelText("Job title"), "Staff Engineer");
    await pasteInto(within(dialog).getByLabelText("Annual salary"), "130000");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create offer" }));

    expect(await within(dialog).findByText("Offer already exists")).toBeInTheDocument();
    expect(within(section("offers-ready")).getAllByRole("listitem", { hidden: true })).toHaveLength(1);
  });

  it("filters all offers by status", async () => {
    const backend = fakeOffersBackend({ role: "auditor", offers: [STEP_1, STEP_2, REJECTED] });
    await renderWorkspace(backend);

    await userEvent.selectOptions(screen.getByLabelText("Status"), "rejected");
    await settled();
    const all = section("offers-all");
    expect(within(all).getAllByRole("listitem")).toHaveLength(1);
    expect(within(all).getByText("Engineer o3")).toBeInTheDocument();
    const lastPage = backend.requests.filter((request) => new URL(request.url).pathname === "/v1/offers").at(-1)!;
    expect(new URL(lastPage.url).searchParams.get("status")).toBe("rejected");
  });

  it("pages through offers with the cursor", async () => {
    const many: FakeOffer[] = Array.from({ length: 27 }, (_, index) => fakeOffer(`o${String(index).padStart(2, "0")}`, { status: "approved" }));
    const backend = fakeOffersBackend({ role: "auditor", offers: many });
    await renderWorkspace(backend);

    const all = section("offers-all");
    expect(within(all).getAllByRole("listitem")).toHaveLength(25);
    await userEvent.click(within(all).getByRole("button", { name: "Load more (2 left)" }));
    await settled();
    expect(within(all).getAllByRole("listitem")).toHaveLength(27);
    const lastPage = backend.requests.filter((request) => new URL(request.url).pathname === "/v1/offers").at(-1)!;
    expect(new URL(lastPage.url).searchParams.get("cursor")).toBe("o24");
  });

  it("shows an error with retry when a list fails, and an error in the sheet for a missing offer", async () => {
    let failInbox = true;
    const backend = fakeOffersBackend({
      role: "hiring_manager",
      override: (request) => {
        if (!request.url.includes("awaiting=me") || !failInbox) return undefined;
        failInbox = false;
        return Response.json({ type: "about:blank", title: "Unavailable", status: 503 }, { status: 503 });
      },
    });
    await renderWorkspace(backend, { initialOfferId: "missing" });

    expect(within(sheet()).getByText("Not found")).toBeInTheDocument();
    await userEvent.click(within(sheet()).getByRole("button", { name: "Close" }));

    const inbox = section("offers-inbox");
    expect(within(inbox).getByRole("alert")).toHaveTextContent("Service temporarily unavailable");
    await userEvent.click(within(inbox).getByRole("button", { name: "Retry" }));
    await settled();
    expect(within(inbox).getByText(/Nothing is waiting on you/)).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("falls back to a short id when the candidate cannot be loaded", async () => {
    const backend = fakeOffersBackend({
      role: "auditor",
      offers: [STEP_1],
      override: (request) => (new URL(request.url).pathname.startsWith("/v1/candidate-cases/") ? Response.json({}, { status: 404 }) : undefined),
    });
    await renderWorkspace(backend);
    await waitFor(() => expect(within(section("offers-all")).getByText("Candidate case-o1")).toBeInTheDocument());
  });
});
