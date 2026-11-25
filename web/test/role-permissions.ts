import type { Permission, Role } from "@/lib/actor/actor";

// Copy of ROLE_PERMISSIONS in app/modules/identity/security.py, as served by GET /v1/me.
const MANAGE: Permission[] = [
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
];

export const ROLE_PERMISSIONS: Record<Role, Permission[]> = {
  tenant_admin: MANAGE,
  recruiter: MANAGE,
  auditor: ["audit:read", "tenant:read"],
  hiring_manager: ["tenant:read"],
  interviewer: ["feedback:submit"],
};
