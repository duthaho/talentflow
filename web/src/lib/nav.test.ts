import { describe, expect, it } from "vitest";

import type { Role } from "@/lib/actor/actor";

import { ROLE_PERMISSIONS } from "../../test/role-permissions";

import { isActive, navItem, visibleNav } from "./nav";

const labelsFor = (role: Role) => visibleNav(ROLE_PERMISSIONS[role]).map((item) => item.label);

describe("role-aware navigation", () => {
  it("shows every section to the tenant admin and all but webhooks to the recruiter", () => {
    const hiring = ["Overview", "Candidates", "Interviews", "Offers", "Reports", "Audit log", "Requisitions", "Retention"];
    expect(labelsFor("tenant_admin")).toEqual([...hiring, "Webhooks"]);
    expect(labelsFor("recruiter")).toEqual(hiring);
  });

  it("limits the hiring manager to read-only hiring sections", () => {
    expect(labelsFor("hiring_manager")).toEqual(["Overview", "Candidates", "Offers", "Requisitions"]);
  });

  it("limits the interviewer to interviews", () => {
    expect(labelsFor("interviewer")).toEqual(["Overview", "Interviews"]);
  });

  it("gives the auditor read-only sections and the audit log", () => {
    expect(labelsFor("auditor")).toEqual(["Overview", "Candidates", "Offers", "Audit log", "Requisitions"]);
  });

  it("shows only the overview without permissions", () => {
    expect(visibleNav([]).map((item) => item.label)).toEqual(["Overview"]);
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
