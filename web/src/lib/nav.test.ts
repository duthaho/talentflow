import { describe, expect, it } from "vitest";

import { mockActor } from "@/lib/actor/mock";

import { isActive, navItem, visibleNav } from "./nav";

const TENANT = "00000000-0000-4000-8000-000000000001";
const labelsFor = (subject: string) =>
  visibleNav(mockActor({ subject, tenantId: TENANT, email: "", name: "" }).permissions).map((item) => item.label);

describe("role-aware navigation", () => {
  it("shows every section to the tenant admin and the recruiter", () => {
    const all = ["Overview", "Candidates", "Interviews", "Offers", "Reports", "Audit log", "Retention"];
    expect(labelsFor("00000000-0000-4000-8000-000000000011")).toEqual(all);
    expect(labelsFor("00000000-0000-4000-8000-000000000012")).toEqual(all);
  });

  it("limits the hiring manager to read-only hiring sections", () => {
    expect(labelsFor("00000000-0000-4000-8000-000000000013")).toEqual(["Overview", "Candidates", "Offers"]);
  });

  it("limits the interviewer to interviews", () => {
    expect(labelsFor("00000000-0000-4000-8000-000000000014")).toEqual(["Overview", "Interviews"]);
  });

  it("shows only the overview to an identity without a membership", () => {
    expect(labelsFor("unknown")).toEqual(["Overview"]);
    expect(visibleNav(mockActor({ subject: "00000000-0000-4000-8000-000000000011", tenantId: "other", email: "", name: "" }).permissions)).toHaveLength(1);
  });

  it("marks nested routes active without matching the overview everywhere", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/", "/candidates")).toBe(false);
    expect(isActive("/settings/retention", "/settings/retention/holds")).toBe(true);
    expect(isActive("/offers", "/offers-archive")).toBe(false);
  });

  it("rejects unknown nav items", () => {
    expect(() => navItem("/nope")).toThrow();
  });
});
