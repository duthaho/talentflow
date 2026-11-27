import type { components } from "@/lib/api/schema";

export type WebhookEndpoint = components["schemas"]["WebhookEndpoint"];
export type WebhookDelivery = components["schemas"]["WebhookDelivery"];
export type WebhookEventType = components["schemas"]["WebhookEventType"];
export type EventType = components["schemas"]["EventType"];
export type DeliveryStatus = components["schemas"]["DeliveryStatus"];
export type PlaintextSecret = components["schemas"]["PlaintextSecret"];

export const MAX_EVENT_TYPES = 20;
export const DESCRIPTION_MAX = 200;
export const URL_MAX = 2048;

export const DELIVERY_STATUS_LABELS: Record<DeliveryStatus, string> = {
  pending: "Pending",
  succeeded: "Succeeded",
  dead_lettered: "Dead-lettered",
  cancelled: "Cancelled",
};

const DISABLED_REASON_LABELS: Record<components["schemas"]["DisabledReason"], string> = {
  manual: "Disabled by an admin",
  failing: "Disabled after repeated failures",
  gone: "Disabled: the receiver answered 410 Gone",
};

const ERROR_LABELS: Record<components["schemas"]["AttemptErrorCode"], string> = {
  http_status: "Non-2xx response",
  redirect: "Redirect (not followed)",
  timeout: "Timed out",
  dns_error: "DNS lookup failed",
  connect_error: "Connection failed",
  tls_error: "TLS error",
  blocked_address: "Address not allowed",
  invalid_url: "Invalid URL",
  response_too_large: "Response too large",
};

export const GRACE_PERIODS = [
  { seconds: 86400, label: "24 hours (recommended)" },
  { seconds: 3600, label: "1 hour" },
  { seconds: 0, label: "Expire immediately (after a leak)" },
] as const;

const TERMINAL: ReadonlySet<DeliveryStatus> = new Set(["succeeded", "dead_lettered", "cancelled"]);

export function isTerminal(status: DeliveryStatus): boolean {
  return TERMINAL.has(status);
}

export function canRedeliver(delivery: Pick<WebhookDelivery, "status">, endpoint: Pick<WebhookEndpoint, "status">): boolean {
  return endpoint.status === "enabled" && isTerminal(delivery.status);
}

export function disabledReasonLabel(endpoint: Pick<WebhookEndpoint, "status" | "disabled_reason">): string | null {
  if (endpoint.status === "enabled") return null;
  return endpoint.disabled_reason ? DISABLED_REASON_LABELS[endpoint.disabled_reason] : "Disabled";
}

export function lastResponseLabel(delivery: Pick<WebhookDelivery, "last_status_code" | "last_error_code">): string {
  if (delivery.last_status_code !== null) return `HTTP ${delivery.last_status_code}`;
  if (delivery.last_error_code !== null) return ERROR_LABELS[delivery.last_error_code] ?? delivery.last_error_code;
  return "—";
}

export function redeliveryOutcome(delivery: WebhookDelivery): string {
  const response = lastResponseLabel(delivery);
  switch (delivery.status) {
    case "succeeded":
      return `Redelivery succeeded (${response}).`;
    case "pending":
      return delivery.attempt_count === 0
        ? "Redelivery queued. Waiting for the first attempt…"
        : `Attempt ${delivery.attempt_count} failed (${response}). Retrying on the normal schedule.`;
    case "dead_lettered":
      return `Redelivery failed after ${delivery.attempt_count} attempts (${response}).`;
    case "cancelled":
      return "Redelivery was cancelled because the endpoint was disabled or deleted.";
  }
}

export function isStale(problem: { status: number }): boolean {
  return problem.status === 412 || problem.status === 404;
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function validateEndpointDraft(draft: { url: string; description: string; eventTypes: readonly string[] }): Partial<Record<"url" | "description" | "event_types", string>> {
  const errors: Partial<Record<"url" | "description" | "event_types", string>> = {};
  const url = draft.url.trim();
  if (!url) errors.url = "Enter the receiver URL.";
  else if (url.length > URL_MAX) errors.url = `Keep the URL to ${URL_MAX} characters or fewer.`;
  else {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "https:" && parsed.protocol !== "http:") errors.url = "Use an https:// URL.";
    } catch {
      errors.url = "Enter an absolute URL, for example https://hooks.example.com/talentflow.";
    }
  }
  if (draft.description.length > DESCRIPTION_MAX) errors.description = `Keep the description to ${DESCRIPTION_MAX} characters or fewer.`;
  else if (/[\u0000-\u001f\u007f]/.test(draft.description)) errors.description = "Remove line breaks and control characters.";
  if (draft.eventTypes.length === 0) errors.event_types = "Pick at least one event.";
  else if (draft.eventTypes.length > MAX_EVENT_TYPES) errors.event_types = `Pick at most ${MAX_EVENT_TYPES} events.`;
  return errors;
}
