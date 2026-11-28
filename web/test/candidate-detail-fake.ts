import { vi } from "vitest";

import type { Permission } from "@/lib/actor/actor";
import { createApiClient } from "@/lib/api/client";
import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import type { Attachment, AttachmentPolicy, CandidateCaseDetail, CaseAuditEvent, LegalHold } from "@/lib/candidates/detail";

// In-memory stand-in for the DUTH-110 read routes and the attachment routes, enforcing the same
// permission per route as app/api/*_router.py so the panels' 403 states can be exercised.
export const PDF = "application/pdf";
export const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export const CASE: CandidateCaseDetail = {
  id: "case-1",
  requisition_id: "req-1",
  first_name: "Ada",
  last_name: "Lovelace",
  email: "ada@example.test",
  stage: "screening",
  version: 2,
  source: "staff",
  created_at: "2026-11-20T09:00:00Z",
};

export function auditEvent(id: string, overrides: Partial<CaseAuditEvent> = {}): CaseAuditEvent {
  return {
    id,
    action: "candidate_case.stage_transitioned",
    aggregate_type: "candidate_case",
    aggregate_id: CASE.id,
    actor_id: "user-me",
    occurred_at: "2026-11-21T10:15:00Z",
    metadata: { from_stage: "applied", to_stage: "screening", version: 2 },
    ...overrides,
  };
}

export function attachment(id: string, overrides: Partial<Attachment> = {}): Attachment {
  return {
    id,
    document_type: "resume",
    filename: `${id}.pdf`,
    content_type: PDF,
    size_bytes: 2048,
    sha256: "0".repeat(64),
    created_at: "2026-11-21T11:00:00Z",
    ...overrides,
  };
}

function problem(status: number, slug: string, detail: string) {
  return Response.json(
    { type: `${PROBLEM_TYPE_BASE}${slug}`, title: slug, status, detail, correlation_id: "corr-1" },
    { status, headers: { "content-type": "application/problem+json" } },
  );
}

type Handler = (request: Request) => Response | Promise<Response> | undefined;

export function fakeDetailBackend({
  permissions,
  candidate = CASE,
  attachments = [],
  events = [],
  hold = { held: false, reason: null, placed_at: null, placed_by: null },
  retentionDays = 90,
  policy = { max_bytes: 1024, allowed_content_types: [DOCX, PDF] },
  override,
}: {
  permissions: Permission[];
  candidate?: CandidateCaseDetail | null;
  attachments?: Attachment[];
  events?: CaseAuditEvent[];
  hold?: LegalHold;
  retentionDays?: number | null;
  policy?: AttachmentPolicy;
  override?: Handler;
}) {
  const files = [...attachments];
  const requests: Request[] = [];
  const allowed = (permission: Permission) => permissions.includes(permission);
  const caseFor = (id: string) => (candidate && candidate.id === id ? candidate : null);

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request.clone());
    const overridden = await override?.(request.clone());
    if (overridden) return overridden;
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "GET" && path === "/v1/attachment-policy") {
      return allowed("tenant:read") ? Response.json(policy) : problem(403, "forbidden", "Forbidden");
    }
    if (request.method === "GET" && path === "/v1/retention-policy") {
      return allowed("retention:manage") ? Response.json({ retention_days: retentionDays }) : problem(403, "forbidden", "Forbidden");
    }

    const match = path.match(/^\/v1\/candidate-cases\/([^/]+)(\/.*)?$/);
    if (!match) return problem(404, "not-found", `No fake for ${request.method} ${path}`);
    const [, id, rest = ""] = match;
    const required: Record<string, Permission> = {
      "": "tenant:read",
      "/attachments": "candidate:attachment",
      "/audit-events": "audit:read",
      "/legal-hold": "retention:manage",
    };
    const permission = required[rest];
    if (!permission) return problem(404, "not-found", `No fake for ${request.method} ${path}`);
    if (!allowed(permission)) return problem(403, "forbidden", "Forbidden");
    const item = caseFor(id);
    if (!item) return problem(404, "not-found", "Candidate case not found");

    if (request.method === "GET" && rest === "") return Response.json(item);
    if (request.method === "GET" && rest === "/legal-hold") return Response.json(hold);
    if (request.method === "GET" && rest === "/attachments") return Response.json(files);
    if (request.method === "GET" && rest === "/audit-events") {
      const cursor = url.searchParams.get("cursor");
      const limit = Number(url.searchParams.get("limit") ?? 25);
      const start = cursor ? events.findIndex((event) => event.id === cursor) + 1 : 0;
      const page = events.slice(start, start + limit);
      const next = start + limit < events.length ? page.at(-1)!.id : null;
      return Response.json({ items: page, next_cursor: next });
    }
    if (request.method === "POST" && rest === "/attachments") {
      const form = await request.formData();
      const file = form.get("file") as File;
      const created = attachment(`att-${files.length + 1}`, {
        filename: file.name,
        content_type: file.type,
        size_bytes: file.size,
        document_type: String(form.get("document_type")),
      });
      files.push(created);
      return Response.json(created, { status: 201 });
    }
    return problem(404, "not-found", `No fake for ${request.method} ${path}`);
  });

  return { api: createApiClient({ baseUrl: "http://api.test", fetch: fetchMock }), requests, fetchMock };
}

export function apiProblem(status: number, slug: string, detail: string) {
  return problem(status, slug, detail);
}
