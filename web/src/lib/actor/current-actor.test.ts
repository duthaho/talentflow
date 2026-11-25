import { beforeEach, describe, expect, it, vi } from "vitest";

const env = vi.hoisted(() => ({ actorSource: "api" as "api" | "mock" }));

vi.mock("react", async (original) => ({ ...(await original<typeof import("react")>()), cache: <T>(fn: T) => fn }));
vi.mock("@/lib/config", () => ({ config: () => ({ apiBaseUrl: "http://api:8000", actorSource: env.actorSource }) }));
vi.mock("@/lib/auth/session", () => ({
  requireSession: async () => ({
    subject: "00000000-0000-4000-8000-000000000014",
    tenantId: "00000000-0000-4000-8000-000000000001",
    email: "interviewer@talentflow.local",
    name: "Interviewer Demo",
    accessToken: "token-1",
  }),
}));

const { getCurrentActor } = await import("./current-actor");

describe("getCurrentActor", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the typed mock while the API has no /v1/me", async () => {
    env.actorSource = "mock";
    expect(await getCurrentActor()).toMatchObject({ ok: true, actor: { role: "interviewer", permissions: ["feedback:submit"] } });
  });

  it("maps the /v1/me contract when the API serves it", async () => {
    env.actorSource = "api";
    const fetchMock = vi.fn(async () =>
      Response.json({
        user_id: "u",
        email: "e@x.test",
        tenant_id: "t",
        tenant_name: "Acme",
        role: "recruiter",
        permissions: ["tenant:read"],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    expect(await getCurrentActor()).toEqual({
      ok: true,
      actor: {
        userId: "u",
        email: "e@x.test",
        displayName: "Interviewer Demo",
        tenantId: "t",
        tenantName: "Acme",
        role: "recruiter",
        permissions: ["tenant:read"],
      },
    });
    expect(fetchMock).toHaveBeenCalledWith("http://api:8000/v1/me", expect.objectContaining({ headers: { Authorization: "Bearer token-1" } }));
  });

  it("returns the API problem when /v1/me fails", async () => {
    env.actorSource = "api";
    const problem = { type: "x#forbidden", title: "Forbidden", status: 403 };
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(problem, { status: 403 })));
    expect(await getCurrentActor()).toEqual({ ok: false, problem });
  });

  it("returns an unreachable problem when the API is down", async () => {
    env.actorSource = "api";
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("down"))));
    const result = await getCurrentActor();
    expect(!result.ok && result.problem.status).toBe(0);
  });
});
