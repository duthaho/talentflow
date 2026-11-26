import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, localInputToIso, validateFeedback } from "./format";

describe("interview formatting", () => {
  it("formats instants in the given time zone with its abbreviation", () => {
    expect(formatDateTime("2026-12-01T09:30:00Z", "UTC")).toBe("Dec 1, 2026, 9:30 AM UTC");
    expect(formatDate("2026-12-01T23:30:00Z", "UTC")).toBe("Dec 1, 2026");
    expect(formatDateTime("not a date")).toBe("—");
  });

  it("turns a datetime-local value into an ISO instant and rejects anything else", () => {
    expect(localInputToIso("2026-12-01T09:30")).toBe(new Date(2026, 11, 1, 9, 30).toISOString());
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("2026-12-01")).toBeNull();
    expect(localInputToIso("2026-13-45T99:99")).toBeNull();
  });
});

describe("validateFeedback", () => {
  it("accepts a complete draft and trims the comments", () => {
    expect(validateFeedback({ score: "4", recommendation: "hire", comments: "  Solid system design.  " })).toEqual({
      ok: true,
      body: { score: 4, recommendation: "hire", comments: "Solid system design." },
    });
  });

  it("reports every missing or invalid field", () => {
    expect(validateFeedback({ score: "", recommendation: "maybe", comments: "   " })).toEqual({
      ok: false,
      errors: {
        score: "Choose a score from 1 to 5.",
        recommendation: "Choose a recommendation.",
        comments: "Write a short justification for your score.",
      },
    });
    expect(validateFeedback({ score: "6", recommendation: "hire", comments: "x".repeat(5001) })).toMatchObject({
      ok: false,
      errors: { score: expect.any(String), comments: "Keep comments to 5000 characters or fewer." },
    });
  });
});
