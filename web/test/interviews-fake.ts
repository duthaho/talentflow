import { vi } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import {
  createInterviewsApi,
  type CalendarSubscriptionSummary,
  type CandidateCase,
  type Interviewer,
  type InterviewListItem,
} from "@/lib/interviews/contract";

// In-memory stand-in for GET /v1/interviews and /v1/interviewers (DUTH-108), the existing schedule and
// feedback routes, and the calendar-subscription routes as specified in docs/specs/DUTH-109.md.

export function fakeInterview(id: string, overrides: Partial<InterviewListItem> = {}): InterviewListItem {
  return {
    id,
    candidate_case_id: `case-${id}`,
    candidate_name: `Ada ${id}`,
    requisition_title: "Backend Engineer",
    interviewer_id: "user-me",
    interviewer_email: "interviewer@talentflow.local",
    scheduled_at: "2026-12-01T09:30:00Z",
    feedback_submitted: false,
    ...overrides,
  };
}

export function fakeCandidate(id: string, stage = "interviewing"): CandidateCase {
  return { id, requisition_id: "req-1", first_name: "Grace", last_name: id, email: `${id}@x.test`, stage, version: 1 };
}

function problem(status: number, slug: string, detail: string, extra: object = {}) {
  return Response.json(
    { type: `${PROBLEM_TYPE_BASE}${slug}`, title: slug, status, detail, ...extra },
    { status, headers: { "content-type": "application/problem+json" } },
  );
}

type Handler = (request: Request) => Response | Promise<Response> | undefined;

export function fakeInterviewsBackend({
  actorId = "user-me",
  canManage = false,
  interviews = [],
  interviewers = [],
  candidates = [],
  links = [],
  override,
}: {
  actorId?: string;
  canManage?: boolean;
  interviews?: InterviewListItem[];
  interviewers?: Interviewer[];
  candidates?: CandidateCase[];
  links?: (CalendarSubscriptionSummary & { interviewer_id?: string })[];
  override?: Handler;
}) {
  const store = new Map(interviews.map((item) => [item.id, structuredClone(item)]));
  const subscriptions = new Map(links.map((link) => [link.id, { interviewer_id: actorId, ...structuredClone(link) }]));
  const requests: Request[] = [];
  let created = 0;

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request.clone());
    const overridden = await override?.(request.clone());
    if (overridden) return overridden;
    const url = new URL(request.url);
    const path = url.pathname;
    const query = url.searchParams;

    if (request.method === "GET" && path === "/v1/interviews") {
      const filter = query.get("interviewer");
      const target = filter === "me" ? actorId : filter;
      if (!canManage && target !== null && target !== actorId) return problem(403, "forbidden", "Actor does not have the required permission");
      let items = [...store.values()].sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at) || a.id.localeCompare(b.id));
      if (!canManage || target) items = items.filter((item) => item.interviewer_id === (target ?? actorId));
      const total = items.length;
      const cursor = query.get("cursor");
      if (cursor) items = items.slice(items.findIndex((item) => item.id === cursor) + 1);
      const limit = Number(query.get("limit") ?? 25);
      const page = items.slice(0, limit);
      return Response.json({ items: page, next_cursor: items.length > limit ? page.at(-1)!.id : null, total });
    }

    if (request.method === "GET" && path === "/v1/interviewers") {
      return canManage ? Response.json({ items: interviewers }) : problem(403, "forbidden", "Actor does not have the required permission");
    }

    if (request.method === "GET" && path === "/v1/candidate-cases") {
      const items = candidates.filter((item) => item.stage === query.get("stage"));
      return Response.json({ items, next_cursor: null, total: items.length });
    }

    const schedule = path.match(/^\/v1\/candidate-cases\/([^/]+)\/interviews$/);
    if (request.method === "POST" && schedule) {
      const body = (await request.json()) as { interviewer_id: string; scheduled_at: string };
      const candidate = candidates.find((item) => item.id === schedule[1]);
      const interviewer = interviewers.find((item) => item.id === body.interviewer_id);
      if (!candidate || !interviewer) return problem(404, "not-found", "Candidate case or interviewer not found");
      const id = `new-${++created}`;
      store.set(id, {
        id,
        candidate_case_id: candidate.id,
        candidate_name: `${candidate.first_name} ${candidate.last_name}`,
        requisition_title: "Backend Engineer",
        interviewer_id: interviewer.id,
        interviewer_email: interviewer.email,
        scheduled_at: body.scheduled_at,
        feedback_submitted: false,
      });
      return Response.json({ id, candidate_case_id: candidate.id, interviewer_id: interviewer.id, scheduled_at: body.scheduled_at }, { status: 201 });
    }

    const feedback = path.match(/^\/v1\/interviews\/([^/]+)\/feedback$/);
    if (request.method === "POST" && feedback) {
      const interview = store.get(feedback[1]);
      if (!interview) return problem(404, "not-found", "Interview not found");
      if (interview.interviewer_id !== actorId) return problem(403, "forbidden", "Only the assigned interviewer can submit feedback");
      if (interview.feedback_submitted) return problem(409, "conflict", "Feedback has already been submitted");
      const body = (await request.json()) as { score: number; recommendation: string; comments: string };
      interview.feedback_submitted = true;
      return Response.json({ id: `fb-${interview.id}`, interview_id: interview.id, ...body }, { status: 201 });
    }

    if (path === "/v1/calendar-subscriptions" && request.method === "GET") {
      if (query.get("interviewer") !== "me") return problem(403, "forbidden", "Actor does not have the required permission");
      const items = [...subscriptions.values()]
        .filter((link) => link.interviewer_id === actorId)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map(({ id, created_at, expires_at }) => ({ id, created_at, expires_at }));
      return Response.json(items);
    }

    if (path === "/v1/calendar-subscriptions" && request.method === "POST") {
      const body = (await request.json()) as { interviewer_id?: string | null };
      if (body.interviewer_id && body.interviewer_id !== actorId) return problem(403, "forbidden", "Actor does not have the required permission");
      const id = `sub${++created}abcdef`;
      const createdAt = `2026-11-26T1${created}:00:00Z`;
      subscriptions.set(id, { id, interviewer_id: actorId, created_at: createdAt, expires_at: "2027-02-24T10:00:00Z" });
      return Response.json(
        { id, interviewer_id: actorId, feed_url: `https://talentflow.test/v1/calendar-feeds/secret-token-${created}.ics`, expires_at: "2027-02-24T10:00:00Z" },
        { status: 201 },
      );
    }

    const revoke = path.match(/^\/v1\/calendar-subscriptions\/([^/]+)$/);
    if (request.method === "DELETE" && revoke) {
      const link = subscriptions.get(revoke[1]);
      if (!link || link.interviewer_id !== actorId) return problem(404, "not-found", "Calendar subscription not found");
      subscriptions.delete(link.id);
      return new Response(null, { status: 204 });
    }

    return problem(404, "not-found", `No fake for ${request.method} ${path}`);
  });

  return { api: createInterviewsApi({ baseUrl: "http://api.test", fetch: fetchMock }), requests, store, subscriptions, fetchMock };
}
