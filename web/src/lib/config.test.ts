import { describe, expect, it } from "vitest";

import { loadConfig } from "./config";

describe("loadConfig", () => {
  it("uses local defaults and reuses the public issuer for the back channel", () => {
    const config = loadConfig({} as NodeJS.ProcessEnv);
    expect(config.oidcInternalIssuer).toBe(config.oidcIssuer);
    expect(config.actorSource).toBe("api");
    expect(config.secureCookies).toBe(false);
  });

  it("trims trailing slashes and enables secure cookies on https", () => {
    const config = loadConfig({ APP_BASE_URL: "https://hr.example.test/", API_BASE_URL: "http://api:8000/" } as unknown as NodeJS.ProcessEnv);
    expect(config.appBaseUrl).toBe("https://hr.example.test");
    expect(config.apiBaseUrl).toBe("http://api:8000");
    expect(config.secureCookies).toBe(true);
  });

  it("rejects an unknown actor source", () => {
    expect(() => loadConfig({ ACTOR_SOURCE: "db" } as unknown as NodeJS.ProcessEnv)).toThrow(/ACTOR_SOURCE/);
  });
});
