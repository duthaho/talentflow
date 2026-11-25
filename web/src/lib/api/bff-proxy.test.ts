import { describe, expect, it, vi } from "vitest";

import { createBffProxy } from "./bff-proxy";

function proxy(token: string | undefined, fetchImpl = vi.fn(async () => new Response("{}", { status: 200 }))) {
  return { forward: createBffProxy({ apiBaseUrl: "http://api:8000", accessToken: async () => token, fetch: fetchImpl as never }), fetchImpl };
}

describe("BFF proxy", () => {
  it("returns an unauthorized problem without a session and never calls the API", async () => {
    const { forward, fetchImpl } = proxy(undefined);
    const response = await forward(new Request("http://web/api/tf/v1/candidate-cases"), ["v1", "candidate-cases"]);
    expect(response.status).toBe(401);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(await response.json()).toMatchObject({ type: expect.stringMatching(/#unauthorized$/), instance: "/v1/candidate-cases" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("only proxies /v1 routes", async () => {
    const { forward } = proxy("t");
    expect((await forward(new Request("http://web/api/tf/metrics"), ["metrics"])).status).toBe(404);
    expect((await forward(new Request("http://web/api/tf/v1/../metrics"), ["v1", "..", "metrics"])).status).toBe(404);
  });

  it("forwards the bearer token, query, body and allow-listed headers", async () => {
    const { forward, fetchImpl } = proxy("token-1");
    await forward(
      new Request("http://web/api/tf/v1/candidate-cases/c 1/stage?x=1", {
        method: "PATCH",
        headers: { "content-type": "application/json", "if-match": "3", cookie: "tf_session=secret" },
        body: JSON.stringify({ stage: "screening" }),
      }),
      ["v1", "candidate-cases", "c 1", "stage"],
    );
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [URL, RequestInit];
    expect(url.href).toBe("http://api:8000/v1/candidate-cases/c%201/stage?x=1");
    const headers = init.headers as Headers;
    expect(headers.get("authorization")).toBe("Bearer token-1");
    expect(headers.get("if-match")).toBe("3");
    expect(headers.get("cookie")).toBeNull();
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe('{"stage":"screening"}');
  });

  it("passes API problems through unchanged", async () => {
    const body = { type: "x#forbidden", title: "Forbidden", status: 403, correlation_id: "c" };
    const { forward } = proxy(
      "t",
      vi.fn(async () =>
        new Response(JSON.stringify(body), {
          status: 403,
          headers: { "content-type": "application/problem+json", "x-correlation-id": "c", "set-cookie": "a=b" },
        }),
      ),
    );
    const response = await forward(new Request("http://web/api/tf/v1/audit-events"), ["v1", "audit-events"]);
    expect(response.status).toBe(403);
    expect(response.headers.get("x-correlation-id")).toBe("c");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(await response.json()).toEqual(body);
  });

  it("returns a service-unavailable problem when the API is unreachable", async () => {
    const { forward } = proxy("t", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    const response = await forward(new Request("http://web/api/tf/v1/candidate-cases"), ["v1", "candidate-cases"]);
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ type: expect.stringMatching(/#service-unavailable$/) });
  });
});
