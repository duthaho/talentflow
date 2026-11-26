import { ROLE_LABELS, type Role } from "@/lib/actor/actor";

import type { OfferDecisionValue, OfferStatus } from "./contract";

export const REASON_MAX = 500;

export const STATUS_LABELS: Record<OfferStatus, string> = {
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as OfferStatus] ?? status;
}

export function roleLabel(role: string | null): string | null {
  if (role === null) return null;
  return ROLE_LABELS[role as Role] ?? role;
}

export function formatSalary(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en", { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);
  } catch {
    return `${amount.toLocaleString("en")} ${currency}`;
  }
}

export function formatDecidedAt(value: string | null): string {
  if (value === null) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(date) + " UTC";
}

export function reasonError(decision: OfferDecisionValue, raw: string): string | null {
  const reason = raw.trim();
  if (decision === "rejected" && reason.length === 0) return "Give a reason for the rejection.";
  if (reason.length > REASON_MAX) return `Keep the reason to ${REASON_MAX} characters or fewer.`;
  return null;
}

export function reasonPayload(raw: string): string | null {
  const reason = raw.trim();
  return reason.length === 0 ? null : reason;
}
