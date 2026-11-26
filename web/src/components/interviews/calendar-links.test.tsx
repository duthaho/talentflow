// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";

import { fakeInterviewsBackend } from "../../../test/interviews-fake";
import { CalendarLinks } from "./calendar-links";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const LINK = { id: "linkA1xyz", created_at: "2026-11-01T10:00:00Z", expires_at: "2027-01-30T10:00:00Z" };

function panel(): HTMLElement {
  return document.querySelector<HTMLElement>('section[data-section="calendar-links"]')!;
}

async function renderLinks(backend: ReturnType<typeof fakeInterviewsBackend>) {
  render(<CalendarLinks api={backend.api} />);
  await waitFor(() => expect(panel()).toHaveAttribute("aria-busy", "false"));
}

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
  vi.mocked(toast.success).mockClear();
});

describe("CalendarLinks", () => {
  it("lists only the caller's active links without any feed URL", async () => {
    const backend = fakeInterviewsBackend({ links: [LINK, { id: "other1", created_at: "2026-11-02T10:00:00Z", expires_at: "2027-01-30T10:00:00Z", interviewer_id: "user-bo" }] });
    await renderLinks(backend);

    expect(new URL(backend.requests[0].url).searchParams.get("interviewer")).toBe("me");
    const rows = within(panel()).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Link linkA1");
    expect(rows[0]).toHaveTextContent(/Created Nov 1, 2026 · expires Jan 30, 2027/);
    expect(panel()).not.toHaveTextContent(/calendar-feeds/);
  });

  it("generates a link for the caller and shows its URL once", async () => {
    const user = userEvent.setup();
    const backend = fakeInterviewsBackend({});
    await renderLinks(backend);
    expect(within(panel()).getByText("You have no active calendar links.")).toBeInTheDocument();

    await user.click(within(panel()).getByRole("button", { name: "Generate link" }));
    const dialog = await screen.findByRole("dialog", { name: "Your calendar link" });
    const post = backend.requests.find((request) => request.method === "POST")!;
    expect(await post.json()).toEqual({});
    expect(within(dialog).getByText("Shown only once")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Feed URL")).toHaveValue("https://talentflow.test/v1/calendar-feeds/secret-token-1.ics");

    await user.click(within(dialog).getByRole("button", { name: "Copy link" }));
    expect(await navigator.clipboard.readText()).toBe("https://talentflow.test/v1/calendar-feeds/secret-token-1.ics");
    expect(within(dialog).getByRole("button", { name: "Copied" })).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(within(panel()).getAllByRole("listitem")).toHaveLength(1));
    expect(document.body).not.toHaveTextContent(/secret-token/);
  });

  it("toasts the problem when generating fails", async () => {
    const backend = fakeInterviewsBackend({
      override: (request) =>
        request.method === "POST" ? Response.json({ type: `${PROBLEM_TYPE_BASE}forbidden`, title: "Forbidden", status: 403 }, { status: 403 }) : undefined,
    });
    await renderLinks(backend);

    await userEvent.click(within(panel()).getByRole("button", { name: "Generate link" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("revokes a link after confirmation", async () => {
    const backend = fakeInterviewsBackend({ links: [LINK] });
    await renderLinks(backend);

    await userEvent.click(within(panel()).getByRole("button", { name: "Revoke link linkA1" }));
    const dialog = screen.getByRole("dialog", { name: "Revoke calendar link?" });
    expect(backend.requests.some((request) => request.method === "DELETE")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke link" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(backend.requests.find((request) => request.method === "DELETE")!.url).toBe("http://api.test/v1/calendar-subscriptions/linkA1xyz");
    expect(backend.subscriptions.has(LINK.id)).toBe(false);
    expect(within(panel()).getByText("You have no active calendar links.")).toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith("Link linkA1 revoked. Calendars using it stop updating.");
  });

  it("treats a 404 on revoke as already gone", async () => {
    const backend = fakeInterviewsBackend({ links: [LINK] });
    await renderLinks(backend);
    backend.subscriptions.clear();

    await userEvent.click(within(panel()).getByRole("button", { name: "Revoke link linkA1" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke link" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Link linkA1 was already revoked or expired."));
    expect(within(panel()).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("keeps the confirmation open when revoking fails", async () => {
    const backend = fakeInterviewsBackend({
      links: [LINK],
      override: (request) =>
        request.method === "DELETE" ? Response.json({ type: `${PROBLEM_TYPE_BASE}unavailable`, title: "Service unavailable", status: 503 }, { status: 503 }) : undefined,
    });
    await renderLinks(backend);

    await userEvent.click(within(panel()).getByRole("button", { name: "Revoke link linkA1" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke link" }));

    expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Revoke calendar link?" })).toBeInTheDocument();
    expect(within(panel()).getAllByRole("listitem", { hidden: true })).toHaveLength(1);
  });

  it("shows a load error with a working retry", async () => {
    let fail = true;
    const backend = fakeInterviewsBackend({
      links: [LINK],
      override: () => (fail ? Response.json({ type: `${PROBLEM_TYPE_BASE}unavailable`, title: "Service unavailable", status: 503 }, { status: 503 }) : undefined),
    });
    await renderLinks(backend);

    fail = false;
    await userEvent.click(within(within(panel()).getByRole("alert")).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(within(panel()).getAllByRole("listitem")).toHaveLength(1));
  });
});
