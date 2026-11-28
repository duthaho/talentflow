import { describe, expect, it } from "vitest";

import type { Role } from "@/lib/actor/actor";

import { ROLE_PERMISSIONS } from "../../test/role-permissions";

import { isActive, navItem, visibleNav } from "./nav";

const WEBHOOKS_ON = { webhooks: { enabled: true, deliveryPaused: false } };
const WEBHOOKS_OFF = { webhooks: { enabled: false, deliveryPaused: true } };

const labelsFor = (role: Role, features = WEBHOOKS_ON) => visibleNav({ permissions: ROLE_PERMISSIONS[role], features }).map((item) => item.label);

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
    expect(visibleNav({ permissions: [], features: WEBHOOKS_ON }).map((item) => item.label)).toEqual(["Overview"]);
  });

  it("hides webhooks from the tenant admin while the tenant's release gate is off", () => {
    expect(labelsFor("tenant_admin", WEBHOOKS_OFF)).not.toContain("Webhooks");
    expect(labelsFor("tenant_admin", { webhooks: { enabled: true, deliveryPaused: true } })).toContain("Webhooks");
    expect(labelsFor("recruiter", WEBHOOKS_ON)).not.toContain("Webhooks");
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
