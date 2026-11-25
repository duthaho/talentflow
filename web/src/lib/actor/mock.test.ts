import { describe, expect, it } from "vitest";

import { can } from "./actor";
import { mockActor } from "./mock";

describe("mockActor", () => {
  it("resolves the seeded demo membership and tenant name", () => {
    const actor = mockActor({
      subject: "00000000-0000-4000-8000-000000000013",
      tenantId: "00000000-0000-4000-8000-000000000001",
      email: "manager@talentflow.local",
      name: "Manager Demo",
    });
    expect(actor).toMatchObject({ role: "hiring_manager", tenantName: "TalentFlow Demo", displayName: "Manager Demo" });
    expect(can(actor, "tenant:read")).toBe(true);
    expect(can(actor, "candidate:create")).toBe(false);
  });

  it("falls back to the email for the display name and grants nothing to strangers", () => {
    const actor = mockActor({ subject: "x", tenantId: "t", email: "x@example.test", name: "" });
    expect(actor).toMatchObject({ role: null, permissions: [], displayName: "x@example.test", tenantName: "t" });
  });
});
