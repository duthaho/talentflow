import { describe, expect, it, vi } from "vitest";
import { clientIp } from "./client-ip";
import { forwardApplication } from "./apply-proxy";
import { publicFetch } from "./public-api";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { once } from "node:events";

const deps = {
  apiBaseUrl: "http://api:8000",
  appOrigin: "http://localhost:3000",
  maxBytes: 10,
};
function request(
  body: BodyInit = "application",
  extra: Record<string, string> = {},
) {
  return new Request("http://localhost:3000/api/public/careers/demo/job", {
    method: "POST",
    body,
    headers: {
      origin: deps.appOrigin,
      "content-type": "multipart/form-data; boundary=test",
      "x-talentflow-ip-chain": "1.2.3.4,::ffff:127.0.0.1",
      ...extra,
    },
  });
}

describe("public careers boundary", () => {
  it("uses the socket, validates addresses, and selects explicitly trusted hops", () => {
    const headers = request().headers;
    expect(clientIp(headers, 0)).toBe("::ffff:127.0.0.1");
    expect(clientIp(headers, 1)).toBe("1.2.3.4");
    expect(() => clientIp(headers, 2)).toThrow();
    expect(() => clientIp(headers, -1)).toThrow();
    expect(() =>
      clientIp(new Headers({ "x-talentflow-ip-chain": "not-an-ip" }), 0),
    ).toThrow();
  });

  it("overwrites browser-provided peer metadata at the real socket boundary", async () => {
    createRequire(import.meta.url)("../../../ingress.cjs");
    const server = createServer((req, res) =>
      res.end(String(req.headers["x-talentflow-ip-chain"])),
    );
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    try {
      const address = server.address() as { port: number };
      const response = await fetch(`http://127.0.0.1:${address.port}`, {
        headers: {
          "x-forwarded-for": "1.2.3.4",
          "x-talentflow-ip-chain": "8.8.8.8",
        },
      });
      const ip = clientIp(
        new Headers({ "x-talentflow-ip-chain": await response.text() }),
        0,
      );
      expect(ip).toBe("127.0.0.1");
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("isolates sessions and forwards a fixed allow-list and accurate body length", async () => {
    const upstream = vi.fn().mockResolvedValue(
      new Response('{"status":"received"}', {
        status: 202,
        headers: {
          "content-type": "application/json",
          "retry-after": "10",
          "set-cookie": "bad",
          location: "https://bad",
        },
      }),
    );
    const response = await forwardApplication(
      request("body", {
        authorization: "Bearer secret",
        cookie: "session=secret",
        "x-forwarded-for": "8.8.8.8",
        "x-correlation-id": "id",
      }),
      "demo",
      "job",
      { ...deps, fetch: upstream },
    );
    expect(response.status).toBe(202);
    const init = upstream.mock.calls[0][1] as RequestInit;
    expect(Object.fromEntries((init.headers as Headers).entries())).toEqual({
      "content-type": "multipart/form-data; boundary=test",
      "content-length": "4",
      "x-forwarded-for": "::ffff:127.0.0.1",
      "x-correlation-id": "id",
    });
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(response.headers.has("location")).toBe(false);
    expect(response.headers.get("retry-after")).toBe("10");
  });

  it("rejects cross-origin applications before reading", async () => {
    const upstream = vi.fn();
    expect(
      (
        await forwardApplication(
          request("x", { origin: "https://bad.test" }),
          "demo",
          "job",
          { ...deps, fetch: upstream },
        )
      ).status,
    ).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("counts streamed bytes and cancels on cap+1 despite a lying length", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(65547));
      },
      cancel,
    });
    const req = new Request("http://localhost:3000", {
      method: "POST",
      body: stream,
      duplex: "half",
      headers: Object.fromEntries(request().headers.entries()),
    } as RequestInit);
    const upstream = vi.fn();
    expect(
      (
        await forwardApplication(req, "demo", "job", {
          ...deps,
          fetch: upstream,
        })
      ).status,
    ).toBe(413);
    expect(cancel).toHaveBeenCalled();
    expect(upstream).not.toHaveBeenCalled();
  });

  it("accepts exactly the cap and fails closed when the API is down", async () => {
    const upstream = vi.fn().mockRejectedValue(new Error("down"));
    expect(
      (
        await forwardApplication(
          request(new Uint8Array(65546)),
          "demo",
          "job",
          { ...deps, fetch: upstream },
        )
      ).status,
    ).toBe(503);
    expect(upstream).toHaveBeenCalledOnce();
  });

  it("SSR uses the visitor address and a 60-second cache for both resources", async () => {
    const upstream = vi
      .fn()
      .mockImplementation(() => Promise.resolve(Response.json({})));
    vi.stubGlobal("fetch", upstream);
    try {
      await publicFetch("demo", "requisitions", request().headers);
      await publicFetch("demo", "consent", request().headers);
      for (const call of upstream.mock.calls)
        expect(call[1]).toEqual({
          headers: { "x-forwarded-for": "::ffff:127.0.0.1" },
          next: { revalidate: 60 },
        });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

it("keeps public route groups and helpers independent of session loading", async () => {
  const { readFileSync, readdirSync } = await import("node:fs");
  const { resolve } = await import("node:path");
  const roots = ["src/app/(public)", "src/app/api/public", "src/lib/careers"];
  function check(directory: string) {
    for (const item of readdirSync(directory, { withFileTypes: true })) {
      const path = resolve(directory, item.name);
      if (item.isDirectory()) check(path);
      else if (/\.tsx?$/.test(path) && !path.includes(".test."))
        expect(readFileSync(path, "utf8")).not.toMatch(
          /getSession|requireSession|auth\/session/,
        );
    }
  }
  for (const root of roots) check(resolve(root));
});

it.each(["requisitions", "consent"] as const)(
  "renders unknown tenant %s as a Next 404",
  async (resource) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
    );
    try {
      await expect(
        publicFetch("missing", resource, request().headers),
      ).rejects.toThrow("NEXT_HTTP_ERROR_FALLBACK;404");
    } finally {
      vi.unstubAllGlobals();
    }
  },
);

it("keeps upstream outages distinct from missing careers pages", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 503 })),
  );
  try {
    await expect(
      publicFetch("demo", "requisitions", request().headers),
    ).rejects.toThrow("Careers service temporarily unavailable");
  } finally {
    vi.unstubAllGlobals();
  }
});

it.each<[string, string | null]>([
  ["Request_123.trace-id", "Request_123.trace-id"],
  ["x".repeat(128), "x".repeat(128)],
  ["x".repeat(129), null],
  ["x".repeat(200), null],
  ["forged <script>alert(1)</script>", null],
  ["", null],
])("forwards only validated correlation IDs (%s)", async (value, expected) => {
  const upstream = vi
    .fn()
    .mockResolvedValue(new Response(null, { status: 202 }));
  const response = await forwardApplication(
    request("body", { "x-correlation-id": value }),
    "demo",
    "job",
    { ...deps, fetch: upstream },
  );
  expect(response.status).toBe(202);
  expect(
    (upstream.mock.calls[0][1].headers as Headers).get("x-correlation-id"),
  ).toBe(expected);
});
