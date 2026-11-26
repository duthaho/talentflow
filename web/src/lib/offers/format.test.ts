import { describe, expect, it } from "vitest";

import { formatDecidedAt, formatSalary, reasonError, reasonPayload, roleLabel, statusLabel } from "./format";

describe("offer formatting", () => {
  it("requires a non-blank reason only for rejections, measured after trimming", () => {
    expect(reasonError("rejected", "")).toMatch(/Give a reason/);
    expect(reasonError("rejected", "   ")).toMatch(/Give a reason/);
    expect(reasonError("approved", "   ")).toBeNull();
    expect(reasonError("rejected", ` ${"x".repeat(500)} `)).toBeNull();
    expect(reasonError("approved", "x".repeat(501))).toMatch(/500 characters/);
  });

  it("sends a trimmed reason, or null when blank", () => {
    expect(reasonPayload("  Above band  ")).toBe("Above band");
    expect(reasonPayload("   ")).toBeNull();
  });

  it("formats salary in the offer currency and survives an unknown code", () => {
    expect(formatSalary(120000, "EUR")).toBe("€120,000");
    expect(formatSalary(120000, "ZZ")).toBe("120,000 ZZ");
  });

  it("shows a dash for legacy decisions without a timestamp", () => {
    expect(formatDecidedAt(null)).toBe("—");
    expect(formatDecidedAt("not a date")).toBe("—");
    expect(formatDecidedAt("2026-11-26T10:30:00+00:00")).toBe("Nov 26, 2026, 10:30 AM UTC");
  });

  it("labels known statuses and roles, passing unknown values through", () => {
    expect(statusLabel("pending_approval")).toBe("Pending approval");
    expect(statusLabel("withdrawn")).toBe("withdrawn");
    expect(roleLabel("hiring_manager")).toBe("Hiring manager");
    expect(roleLabel(null)).toBeNull();
  });
});
