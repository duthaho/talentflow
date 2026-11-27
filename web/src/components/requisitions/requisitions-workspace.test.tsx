// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";

import { RequisitionsWorkspace } from "./requisitions-workspace";

function backend({ failUpdate = false, empty = false } = {}) {
  const job = { id: "job-1", title: "Engineer", department: "Engineering", published: false, published_at: null as string | null };
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "PATCH") {
      if (failUpdate) return Response.json({ detail: "Please try again." }, { status: 503 });
      const body = await request.json();
      job.published = body.published;
      job.published_at = body.published ? "2026-11-26T10:00:00Z" : null;
      return Response.json(job);
    }
    const next = new URL(request.url).searchParams.get("cursor");
    return Response.json({ tenant_slug: "acme", items: empty ? [] : next ? [{ ...job, id: "job-2", title: "Designer" }] : [job], next_cursor: !next && !empty ? "job-1" : null, total: empty ? 0 : 2 });
  });
  return { api: createApiClient({ baseUrl: "http://test", fetch: fetcher }), fetcher };
}

describe("requisition publication", () => {
  it("publishes and unpublishes with the returned server state and loads another page", async () => {
    const server = backend();
    render(<RequisitionsWorkspace canPublish api={server.api} />);
    const toggle = await screen.findByRole("switch", { name: "Publish Engineer" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("link", { name: "/careers/acme" })).toHaveAttribute("href", "/careers/acme");
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Designer")).toBeInTheDocument();
    expect(server.fetcher.mock.calls.filter(([request]) => (request as Request).method === "PATCH")).toHaveLength(2);
  });

  it("shows read-only requisitions without a switch", async () => {
    render(<RequisitionsWorkspace canPublish={false} api={backend().api} />);
    expect(await screen.findByText("Engineer")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("keeps the current state and reports a failed publication", async () => {
    render(<RequisitionsWorkspace canPublish api={backend({ failUpdate: true }).api} />);
    const toggle = await screen.findByRole("switch");
    await userEvent.click(toggle);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toBeEnabled();
  });

  it("renders an empty tenant with its careers URL", async () => {
    render(<RequisitionsWorkspace canPublish api={backend({ empty: true }).api} />);
    expect(await screen.findByText("No requisitions yet.")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/careers/acme");
  });
});
