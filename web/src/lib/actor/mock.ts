import type { Actor, Permission, Role } from "./actor";

// Mirrors ROLE_PERMISSIONS in app/modules/identity/security.py and the demo memberships in
// scripts/seed_demo.py. Delete this module once the API serves `GET /v1/me`.
const ROLE_PERMISSIONS: Record<Role, Permission[]> = {
  tenant_admin: [
    "requisition:create",
    "candidate:create",
    "candidate:transition",
    "candidate:attachment",
    "calendar:manage",
    "interview:manage",
    "audit:read",
    "report:read",
    "tenant:read",
    "retention:manage",
    "retention:purge",
  ],
  recruiter: [
    "requisition:create",
    "candidate:create",
    "candidate:transition",
    "candidate:attachment",
    "calendar:manage",
    "interview:manage",
    "audit:read",
    "report:read",
    "tenant:read",
    "retention:manage",
    "retention:purge",
  ],
  auditor: ["audit:read", "tenant:read"],
  hiring_manager: ["tenant:read"],
  interviewer: ["feedback:submit"],
};

const DEMO_TENANT = { id: "00000000-0000-4000-8000-000000000001", name: "TalentFlow Demo" };

const DEMO_MEMBERSHIPS: Record<string, Role> = {
  "00000000-0000-4000-8000-000000000011": "tenant_admin",
  "00000000-0000-4000-8000-000000000012": "recruiter",
  "00000000-0000-4000-8000-000000000013": "hiring_manager",
  "00000000-0000-4000-8000-000000000014": "interviewer",
};

export function mockActor(identity: { subject: string; tenantId: string; email: string; name: string }): Actor {
  const role = identity.tenantId === DEMO_TENANT.id ? (DEMO_MEMBERSHIPS[identity.subject] ?? null) : null;
  return {
    userId: identity.subject,
    email: identity.email,
    displayName: identity.name || identity.email,
    tenantId: identity.tenantId,
    tenantName: identity.tenantId === DEMO_TENANT.id ? DEMO_TENANT.name : identity.tenantId,
    role,
    permissions: role ? [...ROLE_PERMISSIONS[role]] : [],
  };
}
