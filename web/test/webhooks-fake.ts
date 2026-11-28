import { vi } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import type { WebhookDelivery, WebhookEndpoint, WebhookEventType } from "@/lib/webhooks/format";

// In-memory stand-in for the ADR-008 admin API, following docs/webhooks/openapi.yaml.

export const EVENT_TYPES: WebhookEventType[] = [
  { type: "candidate_case.created.v1", description: "A candidate case was created.", status: "active" },
  { type: "candidate_case.stage_changed.v1", description: "A candidate moved stage.", status: "active" },
  { type: "offer.created.v1", description: "An offer was created.", status: "reserved" },
];

export function fakeEndpoint(id: string, overrides: Partial<WebhookEndpoint> = {}): WebhookEndpoint {
  return {
    id,
    url: `https://${id}.example.com/hooks?token=abc`,
    description: null,
    event_types: ["candidate_case.created.v1"],
    status: "enabled",
    disabled_reason: null,
    consecutive_failures: 0,
    failure_streak_started_at: null,
    secrets: [{ id: `${id}-s1`, status: "current", created_at: "2026-11-20T09:00:00Z", expires_at: null }],
    created_at: "2026-11-20T09:00:00Z",
    updated_at: "2026-11-20T09:00:00Z",
    version: 1,
    ...overrides,
  };
}

export function fakeDelivery(id: string, endpointId: string, overrides: Partial<WebhookDelivery> = {}): WebhookDelivery {
  return {
    id,
    endpoint_id: endpointId,
    event_id: `${id}-event-0000`,
    event_type: "candidate_case.created.v1",
    kind: "fanout",
    status: "succeeded",
    attempt_count: 1,
    max_attempts: 8,
    last_status_code: 204,
    last_error_code: null,
    last_attempt_at: "2026-11-21T10:00:00Z",
    next_attempt_at: null,
    completed_at: "2026-11-21T10:00:00Z",
    created_at: "2026-11-21T10:00:00Z",
    redelivery_of_id: null,
    requested_by: null,
    ...overrides,
  };
}

function problem(status: number, slug: string, detail: string, extra: object = {}) {
  return Response.json({ type: `${PROBLEM_TYPE_BASE}${slug}`, title: slug, status, detail, ...extra }, { status, headers: { "content-type": "application/problem+json" } });
}

type Handler = (request: Request) => Response | Promise<Response> | undefined;

export function fakeWebhooksBackend({
  endpoints = [],
  deliveries = [],
  redeliveryResult = (delivery) => ({ ...delivery, status: "succeeded", attempt_count: 1, last_status_code: 204, completed_at: "2026-11-27T10:00:05Z" }),
  webhooksEnabled = true,
  override,
}: {
  endpoints?: WebhookEndpoint[];
  deliveries?: WebhookDelivery[];
  redeliveryResult?: (pending: WebhookDelivery) => WebhookDelivery;
  webhooksEnabled?: boolean;
  override?: Handler;
} = {}) {
  // Mutable so a test can close the ADR-010 release gate mid-session, as a flagd reload would.
  const gate = { enabled: webhooksEnabled };
  const store = new Map(endpoints.map((item) => [item.id, structuredClone(item)]));
  const log = new Map(deliveries.map((item) => [item.id, structuredClone(item)]));
  const requests: Request[] = [];
  let sequence = 0;

  function bump(endpoint: WebhookEndpoint) {
    endpoint.version += 1;
    endpoint.updated_at = "2026-11-27T10:00:00Z";
  }

  function precondition(request: Request, endpoint: WebhookEndpoint) {
    const header = request.headers.get("if-match");
    if (header === null) return problem(428, "precondition-required", "If-Match is required.");
    if (header !== `"${endpoint.version}"`) return problem(412, "precondition-failed", "The endpoint changed. Reload and try again.", { current_version: endpoint.version });
    return undefined;
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request.clone());
    const overridden = await override?.(request.clone());
    if (overridden) return overridden;
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    if (!gate.enabled && (await gatedOff(request.clone(), method, path))) {
      return problem(403, "feature-disabled", "Webhooks are not enabled for this organization. Existing endpoints can still be viewed, disabled, rotated or deleted.", {
        feature: "webhooks",
      });
    }

    if (method === "GET" && path === "/v1/webhook-event-types") return Response.json({ items: EVENT_TYPES });

    if (path === "/v1/webhook-endpoints") {
      if (method === "GET") return Response.json({ items: [...store.values()], next_cursor: null });
      const body = (await request.json()) as { url: string; description: string | null; event_types: WebhookEndpoint["event_types"]; enabled: boolean };
      if ([...store.values()].some((item) => item.url === body.url)) return problem(409, "conflict", "Another endpoint already uses this URL.");
      if (!body.url.startsWith("https://")) {
        return problem(422, "webhook-url-not-allowed", "The URL must use https.", { errors: [{ pointer: "/url", detail: "The URL must use https." }] });
      }
      const id = `new-${++sequence}`;
      const created = fakeEndpoint(id, {
        url: body.url,
        description: body.description,
        event_types: body.event_types,
        status: body.enabled ? "enabled" : "disabled",
        disabled_reason: body.enabled ? null : "manual",
      });
      store.set(id, created);
      return Response.json(
        { ...created, secret: { id: `${id}-s1`, value: `whsec_created_${id}` } },
        { status: 201, headers: { "cache-control": "no-store", etag: `"${created.version}"` } },
      );
    }

    const one = path.match(/^\/v1\/webhook-endpoints\/([^/]+)$/);
    if (one) {
      const endpoint = store.get(one[1]);
      if (!endpoint) return problem(404, "not-found", "Endpoint not found.");
      if (method === "GET") return Response.json(endpoint);
      const failed = precondition(request, endpoint);
      if (failed) return failed;
      if (method === "DELETE") {
        store.delete(endpoint.id);
        return new Response(null, { status: 204 });
      }
      const body = (await request.json()) as Partial<{ url: string; description: string | null; event_types: WebhookEndpoint["event_types"]; enabled: boolean }>;
      if (body.url !== undefined) endpoint.url = body.url;
      if (body.description !== undefined) endpoint.description = body.description;
      if (body.event_types !== undefined) endpoint.event_types = body.event_types;
      if (body.enabled !== undefined) {
        endpoint.status = body.enabled ? "enabled" : "disabled";
        endpoint.disabled_reason = body.enabled ? null : "manual";
        if (body.enabled) endpoint.consecutive_failures = 0;
      }
      bump(endpoint);
      return Response.json(endpoint, { headers: { etag: `"${endpoint.version}"` } });
    }

    const rotation = path.match(/^\/v1\/webhook-endpoints\/([^/]+)\/secret-rotations$/);
    if (rotation && method === "POST") {
      const endpoint = store.get(rotation[1]);
      if (!endpoint) return problem(404, "not-found", "Endpoint not found.");
      const failed = precondition(request, endpoint);
      if (failed) return failed;
      const { grace_period_seconds: grace } = (await request.json()) as { grace_period_seconds: number };
      const expires = grace === 0 ? "2026-11-27T10:00:00Z" : "2026-11-28T10:00:00Z";
      const secretId = `${endpoint.id}-s${++sequence + 1}`;
      endpoint.secrets = [
        { id: secretId, status: "current", created_at: "2026-11-27T10:00:00Z", expires_at: null },
        ...(grace === 0 ? [] : [{ ...endpoint.secrets[0], status: "previous" as const, expires_at: expires }]),
      ];
      bump(endpoint);
      return Response.json(
        { endpoint, secret: { id: secretId, value: `whsec_rotated_${secretId}` }, previous_secret_expires_at: expires },
        { status: 201, headers: { "cache-control": "no-store", etag: `"${endpoint.version}"` } },
      );
    }

    const list = path.match(/^\/v1\/webhook-endpoints\/([^/]+)\/deliveries$/);
    if (list && method === "GET") {
      if (!store.has(list[1])) return problem(404, "not-found", "Endpoint not found.");
      const statuses = url.searchParams.getAll("status");
      const items = [...log.values()]
        .filter((item) => item.endpoint_id === list[1])
        .filter((item) => statuses.length === 0 || statuses.includes(item.status))
        .sort((a, b) => b.created_at.localeCompare(a.created_at));
      return Response.json({ items, next_cursor: null });
    }

    const detail = path.match(/^\/v1\/webhook-deliveries\/([^/]+)$/);
    if (detail && method === "GET") {
      const delivery = log.get(detail[1]);
      if (!delivery) return problem(404, "not-found", "Delivery not found.");
      if (delivery.status === "pending") {
        const next = redeliveryResult(delivery);
        log.set(delivery.id, next);
        return Response.json({ ...next, attempts: [] });
      }
      return Response.json({ ...delivery, attempts: [] });
    }

    const redelivery = path.match(/^\/v1\/webhook-deliveries\/([^/]+)\/redeliveries$/);
    if (redelivery && method === "POST") {
      const original = log.get(redelivery[1]);
      if (!original) return problem(404, "not-found", "Delivery not found.");
      const endpoint = store.get(original.endpoint_id);
      if (original.status === "pending" || endpoint?.status !== "enabled") {
        return problem(409, "delivery-not-redeliverable", "This delivery cannot be redelivered: the endpoint is disabled.");
      }
      const id = `re-${++sequence}`;
      const pending = fakeDelivery(id, original.endpoint_id, {
        event_id: original.event_id,
        event_type: original.event_type,
        kind: "redelivery",
        status: "pending",
        attempt_count: 0,
        last_status_code: null,
        last_error_code: null,
        last_attempt_at: null,
        completed_at: null,
        next_attempt_at: "2026-11-27T10:00:00Z",
        created_at: "2026-11-27T10:00:00Z",
        redelivery_of_id: original.id,
        requested_by: "user-admin",
      });
      log.set(id, pending);
      bump(endpoint);
      return Response.json(pending, { status: 202, headers: { location: `/v1/webhook-deliveries/${id}` } });
    }

    return problem(404, "not-found", `No fake route for ${method} ${path}`);
  });

  const api = createApiClient({ baseUrl: "http://api.test", fetch: fetchMock as unknown as typeof fetch });
  return { api, requests, fetchMock, store, log, gate };
}

// ADR-010 §3: with the gate off only create, redeliver and a PATCH other than exactly {"enabled": false} are refused.
async function gatedOff(request: Request, method: string, path: string): Promise<boolean> {
  if (method === "POST" && path === "/v1/webhook-endpoints") return true;
  if (method === "POST" && path.endsWith("/redeliveries")) return true;
  if (method === "PATCH") {
    const body = (await request.json()) as Record<string, unknown>;
    return !(Object.keys(body).length === 1 && body.enabled === false);
  }
  return false;
}
