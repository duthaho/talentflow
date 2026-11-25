import { describe, expect, it } from "vitest";

import { isSameOrigin } from "./same-origin";

const request = (headers: Record<string, string>) => new Request("http://web/auth/logout", { method: "POST", headers });

describe("isSameOrigin", () => {
  it("trusts a matching Origin header", () => {
    expect(isSameOrigin(request({ origin: "http://web" }), "http://web")).toBe(true);
    expect(isSameOrigin(request({ origin: "http://web:4000" }), "http://web")).toBe(false);
  });

  it("falls back to Sec-Fetch-Site and rejects requests with neither", () => {
    expect(isSameOrigin(request({ "sec-fetch-site": "same-origin" }), "http://web")).toBe(true);
    expect(isSameOrigin(request({ "sec-fetch-site": "same-site" }), "http://web")).toBe(false);
    expect(isSameOrigin(request({}), "http://web")).toBe(false);
  });
});
