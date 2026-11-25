import { describe, expect, it } from "vitest";

import { describeProblem, fallbackProblem, isProblem, PROBLEM_TYPE_BASE, toProblem } from "./problem";

const problem = (slug: string, status: number, extra: object = {}) => ({
  type: `${PROBLEM_TYPE_BASE}${slug}`,
  title: "T",
  status,
  detail: "server detail",
  correlation_id: "corr-1",
  ...extra,
});

describe("describeProblem", () => {
  it.each([
    ["unauthorized", 401, "unauthenticated"],
    ["forbidden", 403, "forbidden"],
    ["not-found", 404, "not-found"],
    ["version-conflict", 409, "conflict"],
    ["conflict", 409, "conflict"],
    ["validation-error", 422, "validation"],
    ["rate-limited", 429, "rate-limited"],
    ["service-unavailable", 503, "unavailable"],
    ["internal-error", 500, "error"],
  ])("maps the %s problem type to %s", (slug, status, kind) => {
    expect(describeProblem(problem(slug, status)).kind).toBe(kind);
  });

  it("falls back to the HTTP status for unknown problem types", () => {
    expect(describeProblem({ type: "about:blank", title: "x", status: 403 }).kind).toBe("forbidden");
    expect(describeProblem({ type: "about:blank", title: "x", status: 418 }).kind).toBe("error");
  });

  it("shows the server detail and correlation id for client errors", () => {
    const view = describeProblem(problem("forbidden", 403));
    expect(view.description).toBe("server detail");
    expect(view.correlationId).toBe("corr-1");
    expect(view.retryable).toBe(false);
  });

  it("never shows server detail for internal errors and marks them retryable", () => {
    const view = describeProblem(problem("internal-error", 500));
    expect(view.description).not.toContain("server detail");
    expect(view.retryable).toBe(true);
  });

  it("exposes validation field errors", () => {
    const errors = [{ pointer: "/email", detail: "invalid" }];
    expect(describeProblem(problem("validation-error", 422, { errors })).fieldErrors).toEqual(errors);
  });
});

describe("toProblem", () => {
  it("keeps a Problem Details body", () => {
    const body = problem("conflict", 409);
    expect(isProblem(body)).toBe(true);
    expect(toProblem(409, body)).toBe(body);
  });

  it("builds a fallback problem when the body is not Problem Details", () => {
    expect(isProblem("<html>")).toBe(false);
    expect(toProblem(502, "<html>")).toMatchObject({ status: 502, type: "about:blank" });
    expect(fallbackProblem(0).detail).toMatch(/could not be reached/);
  });
});
