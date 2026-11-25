// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";

import { ProblemView } from "./problem-view";
import { toastProblem } from "./toast-problem";

vi.mock("sonner", () => ({ toast: { error: vi.fn(() => "toast-id") } }));

describe("ProblemView", () => {
  it("renders a forbidden problem with its detail and reference", () => {
    render(
      <ProblemView
        problem={{ type: `${PROBLEM_TYPE_BASE}forbidden`, title: "Forbidden", status: 403, detail: "No audit access", correlation_id: "corr-9" }}
      />,
    );
    expect(screen.getByRole("heading", { name: "You don't have access" })).toBeInTheDocument();
    expect(screen.getByText("No audit access")).toBeInTheDocument();
    expect(screen.getByText("corr-9")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("offers sign-in for an unauthenticated problem", () => {
    render(<ProblemView problem={{ type: `${PROBLEM_TYPE_BASE}unauthorized`, title: "Unauthorized", status: 401 }} />);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/auth/login");
  });

  it("offers a retry for transient failures and lists field errors", () => {
    render(
      <ProblemView
        retryHref="/candidates"
        problem={{
          type: `${PROBLEM_TYPE_BASE}validation-error`,
          title: "Unprocessable Content",
          status: 422,
          errors: [{ pointer: "/email", detail: "Invalid email" }],
        }}
      />,
    );
    expect(screen.getByText("/email")).toBeInTheDocument();
    render(<ProblemView retryHref="/candidates" problem={{ type: "about:blank", title: "x", status: 503 }} />);
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute("href", "/candidates");
  });
});

describe("toastProblem", () => {
  it("shows the same title and reference as the page view", async () => {
    const { toast } = await import("sonner");
    toastProblem({ type: `${PROBLEM_TYPE_BASE}version-conflict`, title: "Conflict", status: 409, detail: "Stale version", correlation_id: "c-1" });
    expect(toast.error).toHaveBeenCalledWith(
      "Someone else changed this",
      expect.objectContaining({ id: "c-1", description: "Stale version Reference: c-1", action: undefined }),
    );
  });

  it("adds a sign-in action for an ended session", async () => {
    const { toast } = await import("sonner");
    toastProblem({ type: `${PROBLEM_TYPE_BASE}unauthorized`, title: "Unauthorized", status: 401 });
    const options = vi.mocked(toast.error).mock.calls.at(-1)?.[1] as { action?: { label: string } };
    expect(options.action?.label).toBe("Sign in");
  });
});
