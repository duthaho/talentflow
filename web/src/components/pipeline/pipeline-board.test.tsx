// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import type { Candidate } from "@/lib/pipeline/board-state";

import { PipelineBoard, type BoardPermissions } from "./pipeline-board";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const REQ = "11111111-1111-4111-8111-111111111111";
const RECRUITER: BoardPermissions = { transition: true, createCandidate: true, createRequisition: true };
const HIRING_MANAGER: BoardPermissions = { transition: false, createCandidate: false, createRequisition: false };

function candidate(id: string, stage: string, version = 1): Candidate {
  return { id, requisition_id: REQ, first_name: "Ada", last_name: id, email: `${id}@x.test`, stage, version };
}

type Handler = (request: Request) => Response | Promise<Response>;

const OTHER = "33333333-3333-4333-8333-333333333333";
const REQUISITIONS = [
  { id: REQ, title: "Platform Engineer", department: "Eng" },
  { id: OTHER, title: "Product Designer", department: "Design" },
];

function fakeApi(
  candidates: Candidate[],
  overrides: { patch?: Handler; list?: Handler; post?: Handler; requisitions?: Handler } = {},
) {
  const requests: Request[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request.clone());
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/v1/candidate-cases") {
      if (overrides.list) return overrides.list(request);
      const stage = url.searchParams.get("stage");
      const items = candidates.filter((item) => item.stage === stage);
      return Response.json({ items, next_cursor: null, total: items.length });
    }
    if (request.method === "GET" && url.pathname === "/v1/requisitions") {
      if (overrides.requisitions) return overrides.requisitions(request);
      return Response.json({ items: REQUISITIONS, next_cursor: null, total: REQUISITIONS.length });
    }
    if (request.method === "PATCH" && overrides.patch) return overrides.patch(request);
    if (request.method === "POST" && overrides.post) return overrides.post(request);
    return Response.json({ type: "about:blank", title: "Not Found", status: 404 }, { status: 404 });
  });
  return { api: createApiClient({ baseUrl: "http://api.test", fetch: fetchMock }), requests, fetchMock };
}

function column(stage: string): HTMLElement {
  return document.querySelector<HTMLElement>(`section[data-stage="${stage}"]`)!;
}

function card(id: string): HTMLElement {
  return document.querySelector<HTMLElement>(`li[data-candidate-id="${id}"]`)!;
}

async function renderBoard(api: ReturnType<typeof fakeApi>["api"], permissions = RECRUITER, requisition: string | null = REQ) {
  render(<PipelineBoard api={api} permissions={permissions} initialRequisitionId={requisition} />);
  await waitFor(() => expect(document.querySelectorAll('[aria-busy="true"]')).toHaveLength(0));
}

function candidateLists(requests: Request[]) {
  return requests.filter((request) => request.method === "GET" && new URL(request.url).pathname === "/v1/candidate-cases");
}

function dataTransfer() {
  return { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
}

beforeEach(() => window.history.replaceState(null, "", "/candidates"));

describe("PipelineBoard", () => {
  it("loads one page per stage, filtered by requisition", async () => {
    const { api, requests } = fakeApi([candidate("c1", "applied"), candidate("c2", "screening")]);
    await renderBoard(api);

    const lists = candidateLists(requests).map((request) => new URL(request.url).searchParams);
    expect(lists.map((params) => params.get("stage"))).toHaveLength(9);
    expect(lists.every((params) => params.get("requisition_id") === REQ && params.get("limit") === "20")).toBe(true);
    expect(within(column("applied")).getByText("Ada c1")).toBeInTheDocument();
    expect(within(column("screening")).getByText("Ada c2")).toBeInTheDocument();
    expect(within(column("hired")).getByText("No candidates")).toBeInTheDocument();
  });

  it("makes only state-machine targets droppable while dragging", async () => {
    const { api } = fakeApi([candidate("c1", "applied")]);
    await renderBoard(api);

    fireEvent.dragStart(card("c1"), { dataTransfer: dataTransfer() });
    const droppable = [...document.querySelectorAll("section[data-droppable]")].map((section) => section.getAttribute("data-stage"));
    expect(droppable).toEqual(["screening", "rejected", "withdrawn"]);

    const blocked = new Event("dragover", { bubbles: true, cancelable: true });
    column("hired").dispatchEvent(blocked);
    expect(blocked.defaultPrevented).toBe(false);
  });

  it("drops a card with expected_version and moves it to the new stage", async () => {
    const { api, requests } = fakeApi([candidate("c1", "applied", 3)], {
      patch: () => Response.json(candidate("c1", "screening", 4)),
    });
    await renderBoard(api);

    fireEvent.dragStart(card("c1"), { dataTransfer: dataTransfer() });
    fireEvent.drop(column("screening"), { dataTransfer: dataTransfer() });

    await waitFor(() => expect(within(column("screening")).getByText("Ada c1")).toBeInTheDocument());
    expect(within(column("applied")).queryByText("Ada c1")).not.toBeInTheDocument();
    const patch = requests.find((request) => request.method === "PATCH")!;
    expect(new URL(patch.url).pathname).toBe("/v1/candidate-cases/c1/stage");
    expect(await patch.json()).toEqual({ target_stage: "screening", expected_version: 3 });
  });

  it("ignores a drop on a stage the state machine does not allow", async () => {
    const { api, requests } = fakeApi([candidate("c1", "applied")]);
    await renderBoard(api);

    fireEvent.dragStart(card("c1"), { dataTransfer: dataTransfer() });
    fireEvent.drop(column("hired"), { dataTransfer: dataTransfer() });

    expect(requests.some((request) => request.method === "PATCH")).toBe(false);
    expect(within(column("applied")).getByText("Ada c1")).toBeInTheDocument();
  });

  it("offers only generic endpoint targets in the keyboard Move to menu", async () => {
    const user = userEvent.setup();
    const { api } = fakeApi([candidate("c1", "interviewing")], { patch: () => Response.json(candidate("c1", "rejected", 2)) });
    await renderBoard(api);

    const menu = screen.getByRole("combobox", { name: "Move Ada c1 to stage" });
    expect(within(menu).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Move to…",
      "Rejected",
      "Withdrawn",
    ]);
    await user.selectOptions(menu, "rejected");
    await waitFor(() => expect(within(column("rejected")).getByText("Ada c1")).toBeInTheDocument());
  });

  it("does not offer approval actions in the keyboard Move to menu", async () => {
    const { api } = fakeApi([candidate("c1", "offer_pending_approval")]);
    await renderBoard(api);

    const menu = screen.getByRole("combobox", { name: "Move Ada c1 to stage" });
    expect(within(menu).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Move to…",
      "Withdrawn",
    ]);
  });

  it("shows a changed-by-someone-else prompt on 409 and refreshes instead of overwriting", async () => {
    const user = userEvent.setup();
    let stage = "applied";
    const { api, requests } = fakeApi([], {
      list: (request) => {
        const items = new URL(request.url).searchParams.get("stage") === stage ? [candidate("c1", stage, stage === "applied" ? 1 : 2)] : [];
        return Response.json({ items, next_cursor: null, total: items.length });
      },
      patch: () => {
        stage = "rejected";
        return Response.json(
          {
            type: `${PROBLEM_TYPE_BASE}version-conflict`,
            title: "Conflict",
            status: 409,
            detail: "Candidate case has changed; refresh and retry",
            current_version: 2,
          },
          { status: 409 },
        );
      },
    });
    await renderBoard(api);

    await user.selectOptions(screen.getByRole("combobox", { name: "Move Ada c1 to stage" }), "screening");

    const prompt = await screen.findByRole("alertdialog", { name: "Changed by someone else" });
    expect(prompt).toHaveTextContent("Your move was not applied");
    expect(within(column("screening")).queryByText("Ada c1")).not.toBeInTheDocument();
    expect(requests.filter((request) => request.method === "PATCH")).toHaveLength(1);

    await user.click(within(prompt).getByRole("button", { name: "Refresh board" }));
    await waitFor(() => expect(within(column("rejected")).getByText("Ada c1")).toBeInTheDocument());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(requests.filter((request) => request.method === "PATCH")).toHaveLength(1);
  });

  it("is read-only for a role without candidate:transition or candidate:create", async () => {
    const { api } = fakeApi([candidate("c1", "applied")]);
    await renderBoard(api, HIRING_MANAGER);

    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
    expect(card("c1")).toHaveAttribute("draggable", "false");
    expect(screen.queryByRole("combobox", { name: /Move/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New candidate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New requisition" })).not.toBeInTheDocument();
  });

  it("shows the API problem when the board cannot load at all", async () => {
    const forbidden = { type: `${PROBLEM_TYPE_BASE}forbidden`, title: "Forbidden", status: 403, detail: "Insufficient permissions" };
    const { api } = fakeApi([], { list: () => Response.json(forbidden, { status: 403 }) });
    await renderBoard(api);

    expect(await screen.findByRole("heading", { name: "You don't have access" })).toBeInTheDocument();
  });

  it("creates a candidate who lands in Applied", async () => {
    const user = userEvent.setup();
    const created = candidate("c9", "applied");
    const { api, requests } = fakeApi([], { post: () => Response.json(created, { status: 201 }) });
    await renderBoard(api);
    expect(screen.getByText(/No candidates in this requisition/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New candidate" }));
    const dialog = screen.getByRole("dialog", { name: "New candidate" });
    await user.type(within(dialog).getByLabelText("First name"), "Ada");
    await user.type(within(dialog).getByLabelText("Last name"), "c9");
    await user.type(within(dialog).getByLabelText("Email"), "c9@x.test");
    await user.click(within(dialog).getByRole("button", { name: "Create candidate" }));

    await waitFor(() => expect(within(column("applied")).getByText("Ada c9")).toBeInTheDocument());
    const post = requests.find((request) => request.method === "POST")!;
    expect(await post.json()).toEqual({ requisition_id: REQ, first_name: "Ada", last_name: "c9", email: "c9@x.test" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the dialog open and shows field errors from a 422", async () => {
    const user = userEvent.setup();
    const { api } = fakeApi([], {
      post: () =>
        Response.json(
          {
            type: `${PROBLEM_TYPE_BASE}validation-error`,
            title: "Unprocessable Content",
            status: 422,
            errors: [{ pointer: "/body/email", detail: "value is not a valid email address" }],
          },
          { status: 422 },
        ),
    });
    await renderBoard(api);

    await user.click(screen.getByRole("button", { name: "New candidate" }));
    const dialog = screen.getByRole("dialog", { name: "New candidate" });
    await user.type(within(dialog).getByLabelText("First name"), "Ada");
    await user.type(within(dialog).getByLabelText("Last name"), "L");
    await user.type(within(dialog).getByLabelText("Email"), "a@b.c");
    await user.click(within(dialog).getByRole("button", { name: "Create candidate" }));

    expect(await within(dialog).findByText("value is not a valid email address")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("creates a requisition and switches the board filter to it", async () => {
    const user = userEvent.setup();
    const NEW = "22222222-2222-4222-8222-222222222222";
    const { api, requests } = fakeApi([], { post: () => Response.json({ id: NEW, title: "Backend Engineer", department: "Eng" }, { status: 201 }) });
    await renderBoard(api, RECRUITER, null);

    await user.click(screen.getByRole("button", { name: "New requisition" }));
    const dialog = screen.getByRole("dialog", { name: "New requisition" });
    await user.type(within(dialog).getByLabelText("Title"), "Backend Engineer");
    await user.type(within(dialog).getByLabelText("Department"), "Eng");
    await user.click(within(dialog).getByRole("button", { name: "Create requisition" }));

    await waitFor(() => expect(screen.getByRole("combobox", { name: "Requisition" })).toHaveValue(NEW));
    expect(screen.getByRole("option", { name: "Backend Engineer" })).toBeInTheDocument();
    expect(window.location.search).toBe(`?requisition=${NEW}`);
    await waitFor(() => expect(requests.some((request) => new URL(request.url).searchParams.get("requisition_id") === NEW)).toBe(true));
  });

  it("lists the tenant's requisitions from the API and keeps the selection in the URL", async () => {
    const user = userEvent.setup();
    const { api, requests } = fakeApi([]);
    await renderBoard(api, RECRUITER, null);

    const list = requests.find((request) => new URL(request.url).pathname === "/v1/requisitions")!;
    expect(new URL(list.url).searchParams.get("limit")).toBe("100");
    const select = screen.getByRole("combobox", { name: "Requisition" });
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All requisitions",
      "Platform Engineer",
      "Product Designer",
    ]);

    await user.selectOptions(select, OTHER);
    expect(window.location.search).toBe(`?requisition=${OTHER}`);
    await waitFor(() => expect(requests.some((request) => new URL(request.url).searchParams.get("requisition_id") === OTHER)).toBe(true));

    await user.selectOptions(select, "");
    expect(window.location.search).toBe("");
  });

  it("follows the requisition cursor to load more options", async () => {
    const user = userEvent.setup();
    const { api } = fakeApi([], {
      requisitions: (request) =>
        new URL(request.url).searchParams.get("cursor") === "req-2"
          ? Response.json({ items: [REQUISITIONS[1]], next_cursor: null, total: 2 })
          : Response.json({ items: [REQUISITIONS[0]], next_cursor: "req-2", total: 2 }),
    });
    await renderBoard(api, RECRUITER, null);

    await user.click(screen.getByRole("button", { name: "Load more requisitions (1 left)" }));
    expect(await screen.findByRole("option", { name: "Product Designer" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Platform Engineer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Load more requisitions/ })).not.toBeInTheDocument();
  });

  it("keeps a URL requisition selectable before its page is loaded", async () => {
    const { api } = fakeApi([], { requisitions: () => Response.json({ items: [REQUISITIONS[1]], next_cursor: "req-2", total: 2 }) });
    await renderBoard(api, RECRUITER, REQ);

    expect(screen.getByRole("combobox", { name: "Requisition" })).toHaveValue(REQ);
    expect(screen.getByRole("option", { name: "Requisition 11111111" })).toBeInTheDocument();
  });

  it("shows a retryable error when requisitions fail to load, without blocking the board", async () => {
    const user = userEvent.setup();
    let fail = true;
    const { api } = fakeApi([candidate("c1", "applied")], {
      requisitions: () =>
        fail
          ? Response.json({ type: "about:blank", title: "Internal Server Error", status: 500 }, { status: 500 })
          : Response.json({ items: REQUISITIONS, next_cursor: null, total: 2 }),
    });
    await renderBoard(api, RECRUITER, null);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load requisitions.");
    expect(within(column("applied")).getByText("Ada c1")).toBeInTheDocument();

    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("option", { name: "Platform Engineer" })).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load requisitions.")).not.toBeInTheDocument();
  });

  it("explains a 403 on the requisition list instead of offering a retry", async () => {
    const forbidden = { type: `${PROBLEM_TYPE_BASE}forbidden`, title: "Forbidden", status: 403, detail: "Insufficient permissions" };
    const { api } = fakeApi([], { requisitions: () => Response.json(forbidden, { status: 403 }) });
    await renderBoard(api, HIRING_MANAGER, null);

    expect(screen.getByText("You don't have permission to list requisitions.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("combobox", { name: "Requisition" })).getAllByRole("option")).toHaveLength(1);
  });

  it("shows an empty state when the tenant has no requisitions", async () => {
    const { api } = fakeApi([], { requisitions: () => Response.json({ items: [], next_cursor: null, total: 0 }) });
    await renderBoard(api, RECRUITER, null);

    expect(screen.getByText("No requisitions yet. Create one with New requisition.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Load more requisitions/ })).not.toBeInTheDocument();
  });

  it("announces requisitions while they load", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    const { api } = fakeApi([], {
      requisitions: async () => {
        await gate;
        return Response.json({ items: REQUISITIONS, next_cursor: null, total: 2 });
      },
    });
    render(<PipelineBoard api={api} permissions={RECRUITER} initialRequisitionId={null} />);

    expect(await screen.findByRole("status")).toHaveTextContent("Loading requisitions…");
    await act(async () => release());
    await waitFor(() => expect(screen.queryByText("Loading requisitions…")).not.toBeInTheDocument());
  });

  it("follows the cursor to load more candidates in a stage", async () => {
    const user = userEvent.setup();
    const { api, requests } = fakeApi([], {
      list: (request) => {
        const params = new URL(request.url).searchParams;
        if (params.get("stage") !== "applied") return Response.json({ items: [], next_cursor: null, total: 0 });
        return params.get("cursor") === "page-2"
          ? Response.json({ items: [candidate("c2", "applied")], next_cursor: null, total: 2 })
          : Response.json({ items: [candidate("c1", "applied")], next_cursor: "page-2", total: 2 });
      },
    });
    await renderBoard(api);

    await user.click(within(column("applied")).getByRole("button", { name: "Load more (1 left)" }));
    await waitFor(() => expect(within(column("applied")).getByText("Ada c2")).toBeInTheDocument());
    expect(within(column("applied")).getByText("Ada c1")).toBeInTheDocument();
    expect(within(column("applied")).queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
    expect(requests.some((request) => new URL(request.url).searchParams.get("cursor") === "page-2")).toBe(true);
  });

  it("ignores responses for a requisition that is no longer selected", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    const { api } = fakeApi([], {
      list: async (request) => {
        const params = new URL(request.url).searchParams;
        if (params.get("requisition_id") === REQ) {
          await gate;
          return Response.json({ items: params.get("stage") === "applied" ? [candidate("stale", "applied")] : [], next_cursor: null, total: 1 });
        }
        return Response.json({ items: [], next_cursor: null, total: 0 });
      },
    });
    render(<PipelineBoard api={api} permissions={RECRUITER} initialRequisitionId={REQ} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Requisition" }), { target: { value: "" } });
    await waitFor(() => expect(within(column("applied")).getByText("No candidates")).toBeInTheDocument());
    await act(async () => release());
    expect(within(column("applied")).queryByText("Ada stale")).not.toBeInTheDocument();
  });
});
