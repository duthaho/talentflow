import { beforeEach, describe, expect, it, vi } from "vitest";

const env = vi.hoisted(() => ({ sessionError: undefined as Error | undefined }));

vi.mock("react", async (original) => ({ ...(await original<typeof import("react")>()), cache: <T>(fn: T) => fn }));
vi.mock("@/lib/config", () => ({ config: () => ({ apiBaseUrl: "http://api:8000" }) }));
vi.mock("@/lib/auth/session", () => ({
  requireSession: async () => {
    if (env.sessionError) throw env.sessionError;
    return {
      subject: "00000000-0000-4000-8000-000000000014",
      tenantId: "00000000-0000-4000-8000-000000000001",
      email: "interviewer@talentflow.local",
      name: "Interviewer Demo",
      accessToken: "token-1",
    };
  },
}));

const { getCurrentActor, toActor } = await import("./current-actor");
const { IdentityProviderUnavailableError } = await import("@/lib/auth/identity-provider");

const ME = {
  user_id: "u",
  email: "e@x.test",
  display_name: null,
  tenant_id: "t",
  tenant_name: "Acme",
  role: "interviewer" as const,
  permissions: ["feedback:submit"],
  features: { onboarding: false, webhooks: { enabled: true, delivery_paused: false } },
};

describe("getCurrentActor", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    env.sessionError = undefined;
  });

  it("reads GET /v1/me with the session's bearer token", async () => {
    const fetchMock = vi.fn(async (request: Request) => {
      expect(request.url).toBe("http://api:8000/v1/me");
      expect(request.headers.get("authorization")).toBe("Bearer token-1");
      return Response.json(ME);
    });
    vi.stubGlobal("fetch", fetchMock);
    expect(await getCurrentActor()).toEqual({
      ok: true,
      actor: {
        userId: "u",
        email: "e@x.test",
        displayName: "Interviewer Demo",
        tenantId: "t",
        tenantName: "Acme",
        role: "interviewer",
        permissions: ["feedback:submit"],
        features: { webhooks: { enabled: true, deliveryPaused: false } },
      },
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("returns the API problem when /v1/me fails", async () => {
    const problem = { type: "x#forbidden", title: "Forbidden", status: 403 };
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(problem, { status: 403 })));
    expect(await getCurrentActor()).toEqual({ ok: false, problem });
  });

  it("returns an unreachable problem when the API is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("down"))));
    const result = await getCurrentActor();
    expect(!result.ok && result.problem.status).toBe(0);
  });

  it("shows a service-unavailable problem when Keycloak is down instead of logging out", async () => {
    env.sessionError = new IdentityProviderUnavailableError("down");
    const result = await getCurrentActor();
    expect(!result.ok && result.problem).toMatchObject({ status: 503, type: expect.stringMatching(/#service-unavailable$/) });
  });

  it("rethrows anything else, such as the sign-in redirect", async () => {
    env.sessionError = new Error("NEXT_REDIRECT");
    await expect(getCurrentActor()).rejects.toThrow("NEXT_REDIRECT");
  });
});

describe("toActor", () => {
  it("falls back to the token email and name when the API has none", () => {
    const actor = toActor({ ...ME, email: null }, { email: "token@x.test", name: "" });
    expect(actor).toMatchObject({ email: "token@x.test", displayName: "token@x.test" });
  });

  it("keeps a null email and uses the user id when nothing else is known", () => {
    expect(toActor({ ...ME, email: null }, { email: "", name: "" })).toMatchObject({ email: null, displayName: "u" });
  });

  it("maps the server-evaluated webhook flags, including the flagd-outage fallback", () => {
    const outage = { onboarding: false, webhooks: { enabled: false, delivery_paused: true } };
    expect(toActor({ ...ME, features: outage }, { email: "", name: "" }).features).toEqual({ webhooks: { enabled: false, deliveryPaused: true } });
  });

  it("drops permissions the web app does not know", () => {
    expect(toActor({ ...ME, permissions: ["feedback:submit", "future:thing"] }, { email: "", name: "" }).permissions).toEqual([
      "feedback:submit",
    ]);
  });
});
