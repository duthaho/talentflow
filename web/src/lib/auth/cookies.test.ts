import { describe, expect, it } from "vitest";

import { loginCookieOptions, sessionCookieOptions } from "./cookies";

describe("cookie options", () => {
  it("makes the session cookie a browser-session cookie so Redis owns the lifetime", () => {
    const options = sessionCookieOptions(true);
    expect(options).not.toHaveProperty("maxAge");
    expect(options).not.toHaveProperty("expires");
    expect(options).toMatchObject({ httpOnly: true, sameSite: "lax", secure: true, path: "/" });
  });

  it("caps the pending-login cookie at the login TTL", () => {
    expect(loginCookieOptions(false, 600)).toMatchObject({ httpOnly: true, secure: false, maxAge: 600 });
  });
});
