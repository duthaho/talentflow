export type Permission =
  | "requisition:create"
  | "candidate:create"
  | "candidate:transition"
  | "candidate:attachment"
  | "calendar:manage"
  | "interview:manage"
  | "feedback:submit"
  | "audit:read"
  | "report:read"
  | "tenant:read"
  | "retention:manage"
  | "retention:purge";

export type Role = "tenant_admin" | "recruiter" | "hiring_manager" | "interviewer" | "auditor";

// Contract proposed for `GET /v1/me`; the API does not expose it yet (see the mock below).
export type Actor = {
  userId: string;
  email: string;
  displayName: string;
  tenantId: string;
  tenantName: string;
  role: Role | null;
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
