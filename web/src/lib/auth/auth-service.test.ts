import { createHash } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthService, LoginError, safeReturnTo } from "./auth-service";
import { IdentityProviderUnavailableError, RefreshRejectedError, type IdentityProvider, type TokenSet } from "./identity-provider";
import { MemoryKeyValueStore, SessionStore } from "./session-store";

const CLAIMS = { sub: "user-1", tenant_id: "tenant-1", email: "a@b.test", name: "Ada" };

function tokens(overrides: Partial<TokenSet> = {}): TokenSet {
  return {
    accessToken: "access-1",
    expiresInSeconds: 300,
    refreshToken: "refresh-1",
    refreshExpiresInSeconds: 1800,
    idToken: "id-1",
    claims: CLAIMS,
    ...overrides,
  };
}

function fakeProvider(): IdentityProvider & { [K in keyof IdentityProvider]: ReturnType<typeof vi.fn> } {
  return {
    authorizationUrl: vi.fn((params) => {
      const url = new URL("http://idp.test/auth");
      url.searchParams.set("state", params.state);
      url.searchParams.set("code_challenge", params.codeChallenge);
      return url;
    }),
    exchangeCode: vi.fn(async () => tokens()),
    refresh: vi.fn(async () => tokens({ accessToken: "access-2", refreshToken: undefined, idToken: undefined })),
    revoke: vi.fn(async () => undefined),
    endSessionUrl: vi.fn(({ idToken, postLogoutRedirectUri }) => {
      const url = new URL("http://idp.test/logout");
      if (idToken) url.searchParams.set("id_token_hint", idToken);
      url.searchParams.set("post_logout_redirect_uri", postLogoutRedirectUri);
      return url;
    }),
  } as never;
}

describe("AuthService", () => {
  let now: number;
  let kv: MemoryKeyValueStore;
  let provider: ReturnType<typeof fakeProvider>;
  let service: AuthService;

  beforeEach(() => {
    now = 1_000_000;
    kv = new MemoryKeyValueStore(() => now);
    provider = fakeProvider();
    service = new AuthService({ provider, store: new SessionStore(kv), appBaseUrl: "http://web.test", now: () => now });
  });

  async function login() {
    const { loginId, authorizationUrl } = await service.beginLogin("/candidates?stage=applied");
    const state = authorizationUrl.searchParams.get("state");
    return service.completeLogin(loginId, `?code=abc&state=${state}`);
  }

  it("starts login with a PKCE S256 challenge derived from a stored verifier", async () => {
    const { authorizationUrl } = await service.beginLogin("/");
    const call = provider.authorizationUrl.mock.calls[0][0];
    expect(call.redirectUri).toBe("http://web.test/auth/callback");
    expect(call.codeChallenge).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(authorizationUrl.searchParams.get("state")).toBe(call.state);
    const checks = provider.authorizationUrl.mock.calls[0][0];
    expect(checks.nonce).toBeTruthy();
  });

  it("exchanges the code with the stored checks and creates a session", async () => {
    const result = await login();
    const [callbackUrl, checks] = provider.exchangeCode.mock.calls[0];
    expect((callbackUrl as URL).href).toMatch(/^http:\/\/web\.test\/auth\/callback\?code=abc/);
    const challenge = provider.authorizationUrl.mock.calls[0][0].codeChallenge;
    expect(createHash("sha256").update(checks.codeVerifier).digest("base64url")).toBe(challenge);
    expect(result).toMatchObject({ returnTo: "/candidates?stage=applied" });
    expect(await service.currentSession(result.sessionId)).toMatchObject({
      subject: "user-1",
      tenantId: "tenant-1",
      name: "Ada",
      accessToken: "access-1",
    });
  });

  it("rejects a replayed or unknown login attempt", async () => {
    const { loginId } = await service.beginLogin("/");
    await service.completeLogin(loginId, "?code=abc&state=s");
    await expect(service.completeLogin(loginId, "?code=abc&state=s")).rejects.toBeInstanceOf(LoginError);
    await expect(service.completeLogin(undefined, "?code=abc")).rejects.toBeInstanceOf(LoginError);
  });

  it("surfaces an error returned by Keycloak without exchanging a code", async () => {
    const { loginId } = await service.beginLogin("/");
    await expect(service.completeLogin(loginId, "?error=access_denied")).rejects.toThrow(/access_denied/);
    expect(provider.exchangeCode).not.toHaveBeenCalled();
  });

  it("rejects tokens without a tenant claim", async () => {
    provider.exchangeCode.mockResolvedValueOnce(tokens({ claims: { sub: "user-1" } }));
    const { loginId } = await service.beginLogin("/");
    await expect(service.completeLogin(loginId, "?code=abc")).rejects.toThrow(/tenant/);
  });

  it("expires pending logins", async () => {
    const { loginId } = await service.beginLogin("/");
    now += 601_000;
    await expect(service.completeLogin(loginId, "?code=abc")).rejects.toBeInstanceOf(LoginError);
  });

  it("refreshes the access token shortly before it expires and keeps the old refresh token", async () => {
    const { sessionId } = await login();
    now += 280_000;
    const session = await service.currentSession(sessionId);
    expect(provider.refresh).toHaveBeenCalledWith("refresh-1");
    expect(session).toMatchObject({ accessToken: "access-2", refreshToken: "refresh-1", idToken: "id-1" });
  });

  it("keeps an active session usable past the first 30-minute TTL", async () => {
    const { sessionId } = await login();
    for (let minute = 5; minute <= 90; minute += 5) {
      now = 1_000_000 + minute * 60_000;
      expect(await service.currentSession(sessionId), `minute ${minute}`).not.toBeNull();
    }
    expect(provider.refresh.mock.calls.length).toBeGreaterThan(5);
  });

  it("expires an idle session when the refresh window passes without activity", async () => {
    const { sessionId } = await login();
    now += 1_801_000;
    expect(await service.currentSession(sessionId)).toBeNull();
    expect(provider.refresh).not.toHaveBeenCalled();
  });

  it("ends the session when Keycloak rejects the refresh token", async () => {
    const { sessionId } = await login();
    provider.refresh.mockRejectedValueOnce(new RefreshRejectedError("invalid_grant"));
    now += 299_000;
    expect(await service.currentSession(sessionId)).toBeNull();
    expect(await service.currentSession(sessionId)).toBeNull();
  });

  it("keeps the session through a transient refresh failure while the access token is still valid", async () => {
    const { sessionId } = await login();
    provider.refresh.mockRejectedValueOnce(new IdentityProviderUnavailableError("down"));
    now += 280_000;
    expect(await service.currentSession(sessionId)).toMatchObject({ accessToken: "access-1" });
    expect(await service.currentSession(sessionId)).toMatchObject({ accessToken: "access-2" });
  });

  it("reports an outage, without logging out, when the access token has already expired", async () => {
    const { sessionId } = await login();
    provider.refresh.mockRejectedValueOnce(new TypeError("fetch failed"));
    now += 301_000;
    await expect(service.currentSession(sessionId)).rejects.toBeInstanceOf(IdentityProviderUnavailableError);
    expect(await service.currentSession(sessionId)).toMatchObject({ accessToken: "access-2" });
  });

  it("returns no session without a cookie or for an unknown id", async () => {
    expect(await service.currentSession(undefined)).toBeNull();
    expect(await service.currentSession("missing")).toBeNull();
  });

  it("logs out by deleting the session, revoking the refresh token and ending the Keycloak session", async () => {
    const { sessionId } = await login();
    provider.revoke.mockRejectedValueOnce(new Error("network"));
    const url = await service.logout(sessionId, "http://web.test/signed-out");
    expect(provider.revoke).toHaveBeenCalledWith("refresh-1");
    expect(url.searchParams.get("id_token_hint")).toBe("id-1");
    expect(url.searchParams.get("post_logout_redirect_uri")).toBe("http://web.test/signed-out");
    expect(await service.currentSession(sessionId)).toBeNull();
  });

  it("still ends the Keycloak session when the local session is already gone", async () => {
    const url = await service.logout(undefined, "http://web.test/signed-out");
    expect(url.searchParams.has("id_token_hint")).toBe(false);
    expect(provider.revoke).not.toHaveBeenCalled();
  });
});

describe("safeReturnTo", () => {
  it.each([
    [null, "/"],
    ["https://evil.test", "/"],
    ["//evil.test", "/"],
    ["/\\evil.test", "/"],
    ["/\t/evil.test", "/"],
    ["/\n/evil.test", "/"],
    ["/candidates#board", "/candidates#board"],
    ["/offers?x=1", "/offers?x=1"],
  ])("maps %s to %s", (input, expected) => {
    expect(safeReturnTo(input)).toBe(expected);
  });
});

describe("SessionStore", () => {
  it("stores sessions under a hash of the cookie value", async () => {
    const kv = new MemoryKeyValueStore();
    const store = new SessionStore(kv);
    await store.saveSession("cookie-value", { subject: "s" } as never, 60);
    const spy = vi.spyOn(kv, "get");
    await store.getSession("cookie-value");
    expect(spy.mock.calls[0][0]).not.toContain("cookie-value");
    expect(spy.mock.calls[0][0]).toMatch(/^tf:web:session:[0-9a-f]{64}$/);
    await store.deleteSession("cookie-value");
    expect(kv.size()).toBe(0);
  });
});
