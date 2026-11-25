import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

const service = vi.hoisted(() => ({
  completeLogin: vi.fn(async () => ({ sessionId: "sid-1", returnTo: "/candidates" })),
  logout: vi.fn(async () => new URL("http://idp.test/logout")),
}));

vi.mock("@/lib/auth/session", () => ({ authService: () => service }));
vi.mock("@/lib/config", () => ({ config: () => ({ appBaseUrl: "http://web.test", secureCookies: false }) }));

const { GET: callback } = await import("./callback/route");
const { POST: logout } = await import("./logout/route");

describe("auth routes", () => {
  it("sets the session cookie without a browser expiry after login", async () => {
    const response = await callback(
      new NextRequest("http://web.test/auth/callback?code=c&state=s", { headers: { cookie: "tf_login=l1" } }),
    );
    expect(response.headers.get("location")).toBe("http://web.test/candidates");
    const setCookie = response.headers.getSetCookie().find((cookie) => cookie.startsWith("tf_session="));
    expect(setCookie).toMatch(/HttpOnly/i);
    expect(setCookie).not.toMatch(/Max-Age|Expires/i);
  });

  it("signs out a same-origin form post", async () => {
    const response = await logout(
      new NextRequest("http://web.test/auth/logout", { method: "POST", headers: { origin: "http://web.test", cookie: "tf_session=sid-1" } }),
    );
    expect(response.status).toBe(303);
    expect(service.logout).toHaveBeenCalledWith("sid-1", "http://web.test/signed-out");
  });

  it("refuses a cross-origin sign-out", async () => {
    service.logout.mockClear();
    const response = await logout(
      new NextRequest("http://web.test/auth/logout", { method: "POST", headers: { origin: "http://localhost:4000" } }),
    );
    expect(response.status).toBe(403);
    expect(service.logout).not.toHaveBeenCalled();
  });
});
