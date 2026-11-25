import type { components } from "@/lib/api/schema";

const PERMISSIONS = [
  "requisition:create",
  "candidate:create",
  "candidate:transition",
  "candidate:attachment",
  "calendar:manage",
  "interview:manage",
  "feedback:submit",
  "audit:read",
  "report:read",
  "tenant:read",
  "retention:manage",
  "retention:purge",
] as const;

export type Permission = (typeof PERMISSIONS)[number];

export type Role = components["schemas"]["CurrentActorResponse"]["role"];

export function isPermission(value: string): value is Permission {
  return (PERMISSIONS as readonly string[]).includes(value);
}

export type Actor = {
  userId: string;
  email: string | null;
  displayName: string;
  tenantId: string;
  tenantName: string;
  role: Role;
  permissions: Permission[];
};

export const ROLE_LABELS: Record<Role, string> = {
  tenant_admin: "Tenant admin",
  recruiter: "Recruiter",
  hiring_manager: "Hiring manager",
  interviewer: "Interviewer",
  auditor: "Auditor",
};

export function can(actor: Pick<Actor, "permissions">, permission: Permission): boolean {
  return actor.permissions.includes(permission);
}
