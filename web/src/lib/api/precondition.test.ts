import { describe, expect, it } from "vitest";

import { ifMatch, isStaleVersion } from "./precondition";

describe("ifMatch", () => {
  it("formats the aggregate version as a strong entity tag", () => {
    expect(ifMatch(3)).toBe('"3"');
    expect(ifMatch(0)).toBe('"0"');
  });
});

describe("isStaleVersion", () => {
  it.each([
    [409, true],
    [412, true],
    [400, false],
    [428, false],
    [403, false],
  ])("status %i -> %s", (status, stale) => {
    expect(isStaleVersion(status)).toBe(stale);
  });
});
