import { describe, expect, it, vi } from "vitest";

import { createApiClient, settle } from "./client";

describe("generated API client", () => {
  it("sends the bearer token and returns typed data", async () => {
    const fetchImpl = vi.fn(async (request: Request) => {
      expect(request.headers.get("authorization")).toBe("Bearer t");
      expect(new URL(request.url).searchParams.get("limit")).toBe("1");
      return Response.json({ items: [], next_cursor: null, total: 7 });
    });
    const api = createApiClient({ baseUrl: "http://api", accessToken: "t", fetch: fetchImpl as never });
    const result = await settle(api.GET("/v1/candidate-cases", { params: { query: { limit: 1 } } }));
    expect(result).toEqual({ ok: true, data: { items: [], next_cursor: null, total: 7 } });
  });

  it("turns error bodies into Problem Details", async () => {
    const problem = { type: "x#forbidden", title: "Forbidden", status: 403 };
    const api = createApiClient({
      baseUrl: "http://api",
      fetch: (async () => Response.json(problem, { status: 403 })) as never,
    });
    expect(await settle(api.GET("/v1/audit-events"))).toEqual({ ok: false, problem });
  });

  it("turns network failures into a status-0 problem", async () => {
    const api = createApiClient({ baseUrl: "http://api", fetch: (async () => Promise.reject(new TypeError("down"))) as never });
    const result = await settle(api.GET("/v1/audit-events"));
    expect(result.ok).toBe(false);
    expect(!result.ok && result.problem.status).toBe(0);
  });
});
