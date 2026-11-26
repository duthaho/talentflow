import { vi } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import { createOffersApi, type CandidateCaseDetail, type OfferDecision, type OfferDetail, type OfferSummary } from "@/lib/offers/contract";

// In-memory stand-in for the DUTH-115 / DUTH-110 routes. The step → role table copies
// ApprovalPolicy.standard() only so the fake can compute can_decide the way the API does.
const STEP_ROLES: Record<number, string> = { 1: "hiring_manager", 2: "tenant_admin" };

export type FakeOffer = Omit<OfferDetail, "awaiting_role" | "can_decide">;

export function candidateCase(id: string, stage = "interviewing"): CandidateCaseDetail {
  return {
    id,
    requisition_id: "req-1",
    first_name: "Ada",
    last_name: id,
    email: `${id}@x.test`,
    stage,
    version: 1,
    created_at: "2026-11-20T09:00:00Z",
  };
}

export function fakeOffer(id: string, overrides: Partial<FakeOffer> = {}): FakeOffer {
  return {
    id,
    candidate_case_id: `case-${id}`,
    title: `Engineer ${id}`,
    annual_salary: 120000,
    currency: "EUR",
    status: "pending_approval",
    approval_step: 1,
    version: 1,
    decisions: [],
    ...overrides,
  };
}

function problem(status: number, slug: string, detail: string, extra: object = {}) {
  return Response.json(
    { type: `${PROBLEM_TYPE_BASE}${slug}`, title: slug, status, detail, ...extra },
    { status, headers: { "content-type": "application/problem+json" } },
  );
}

type Handler = (request: Request) => Response | Promise<Response> | undefined;

export function fakeOffersBackend({
  role,
  actorId = "user-me",
  offers = [],
  candidates = [],
  override,
}: {
  role: string;
  actorId?: string;
  offers?: FakeOffer[];
  candidates?: CandidateCaseDetail[];
  override?: Handler;
}) {
  const store = new Map(offers.map((offer) => [offer.id, structuredClone(offer)]));
  const cases = new Map(candidates.map((item) => [item.id, structuredClone(item)]));
  for (const offer of offers) if (!cases.has(offer.candidate_case_id)) cases.set(offer.candidate_case_id, candidateCase(offer.candidate_case_id, "offer_pending_approval"));
  const requests: Request[] = [];

  function view(offer: FakeOffer): OfferSummary & { decisions: OfferDecision[] } {
    const awaiting = offer.status === "pending_approval" ? STEP_ROLES[offer.approval_step] : null;
    return { ...offer, awaiting_role: awaiting, can_decide: awaiting !== null && awaiting === role };
  }

  function summary(offer: FakeOffer): OfferSummary {
    const { decisions: _decisions, ...rest } = view(offer);
    void _decisions;
    return rest;
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request.clone());
    const overridden = await override?.(request.clone());
    if (overridden) return overridden;
    const url = new URL(request.url);
    const path = url.pathname;
    const query = url.searchParams;

    if (request.method === "GET" && path === "/v1/offers") {
      let items = [...store.values()].sort((a, b) => a.id.localeCompare(b.id));
      if (query.get("awaiting") === "me") items = items.filter((offer) => offer.status === "pending_approval" && STEP_ROLES[offer.approval_step] === role);
      if (query.get("status")) items = items.filter((offer) => offer.status === query.get("status"));
      const total = items.length;
      const cursor = query.get("cursor");
      if (cursor) items = items.filter((offer) => offer.id > cursor);
      const limit = Number(query.get("limit") ?? 25);
      const page = items.slice(0, limit);
      const next = items.length > limit ? page.at(-1)!.id : null;
      return Response.json({ items: page.map(summary), next_cursor: next, total });
    }

    const detail = path.match(/^\/v1\/offers\/([^/]+)$/);
    if (request.method === "GET" && detail) {
      const offer = store.get(detail[1]);
      return offer ? Response.json(view(offer)) : problem(404, "not-found", "Offer not found");
    }

    const approval = path.match(/^\/v1\/offers\/([^/]+)\/approvals$/);
    if (request.method === "POST" && approval) {
      const offer = store.get(approval[1]);
      if (!offer) return problem(404, "not-found", "Offer not found");
      const body = (await request.json()) as { decision: "approved" | "rejected"; expected_version: number; reason?: string | null };
      if (body.decision === "rejected" && !body.reason?.trim()) {
        return problem(422, "validation-error", "Request validation failed", { errors: [{ pointer: "/body/reason", detail: "A rejection needs a reason" }] });
      }
      if (body.expected_version !== offer.version) return problem(409, "version-conflict", "Offer has changed; refresh and retry", { current_version: offer.version });
      if (!view(offer).can_decide) return problem(403, "forbidden", "Actor cannot approve this step");
      offer.decisions.push({ step: offer.approval_step, decision: body.decision, actor_id: actorId, decided_at: "2026-11-26T10:30:00Z", reason: body.reason ?? null });
      offer.version += 1;
      if (body.decision === "rejected") offer.status = "rejected";
      else if (STEP_ROLES[offer.approval_step + 1]) offer.approval_step += 1;
      else offer.status = "approved";
      return Response.json({ id: offer.id, status: offer.status, approval_step: offer.approval_step, version: offer.version, candidate_stage: "offer_pending_approval" });
    }

    const caseDetail = path.match(/^\/v1\/candidate-cases\/([^/]+)$/);
    if (request.method === "GET" && caseDetail) {
      const item = cases.get(caseDetail[1]);
      return item ? Response.json(item) : problem(404, "not-found", "Candidate case not found");
    }

    if (request.method === "GET" && path === "/v1/candidate-cases") {
      const items = [...cases.values()].filter((item) => item.stage === query.get("stage"));
      return Response.json({ items, next_cursor: null, total: items.length });
    }

    const create = path.match(/^\/v1\/candidate-cases\/([^/]+)\/offers$/);
    if (request.method === "POST" && create) {
      const item = cases.get(create[1]);
      if (!item || item.stage !== "interviewing") return problem(409, "conflict", "Candidate must be interviewing before an offer is created");
      const body = (await request.json()) as { title: string; annual_salary: number; currency: string };
      const id = `new-${store.size + 1}`;
      store.set(id, fakeOffer(id, { candidate_case_id: item.id, ...body }));
      item.stage = "offer_pending_approval";
      return Response.json({ id, status: "pending_approval", approval_step: 1, version: 1, candidate_stage: "offer_pending_approval" }, { status: 201 });
    }

    return problem(404, "not-found", `No fake for ${request.method} ${path}`);
  });

  return { api: createOffersApi({ baseUrl: "http://api.test", fetch: fetchMock }), requests, store, fetchMock };
}
