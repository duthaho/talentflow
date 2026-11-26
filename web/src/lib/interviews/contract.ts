import createClient from "openapi-fetch";

import { BROWSER_API_BASE } from "@/lib/api/client";
import type { components, paths } from "@/lib/api/schema";

// Hand-written from docs/specs/DUTH-109.md (AC2, AC5, AC8) until DUTH-109 merges and `make api-client`
// regenerates schema.ts. Delete ContractPaths then and use `paths` directly; the call sites stay the same.

export type InterviewListItem = components["schemas"]["InterviewListItem"];
export type Interviewer = components["schemas"]["InterviewerItem"];
export type CandidateCase = components["schemas"]["CandidateCaseResponse"];
export type Recommendation = "strong_hire" | "hire" | "no_hire" | "strong_no_hire";

export type CalendarSubscription = components["schemas"]["CalendarSubscriptionResponse"];
export type CalendarSubscriptionSummary = { id: string; created_at: string; expires_at: string };

type Json<T> = { headers: { [name: string]: unknown }; content: { "application/json": T } };
type Problem = Json<unknown>;
type NoParams = { query?: never; header?: never; path?: never; cookie?: never };
type Unused = { put?: never; options?: never; head?: never; patch?: never; trace?: never };

type ContractPaths = {
  "/v1/calendar-subscriptions": Unused & {
    parameters: NoParams;
    get: {
      parameters: { query: { interviewer: string }; header?: never; path?: never; cookie?: never };
      requestBody?: never;
      responses: { 200: Json<CalendarSubscriptionSummary[]>; 403: Problem; 422: Problem };
    };
    post: {
      parameters: NoParams;
      requestBody: { content: { "application/json": { interviewer_id?: string | null } } };
      responses: { 201: Json<CalendarSubscription>; 403: Problem; 404: Problem; 422: Problem };
    };
    delete?: never;
  };
  "/v1/calendar-subscriptions/{subscription_id}": Unused & {
    parameters: NoParams;
    get?: never;
    post?: never;
    delete: {
      parameters: { query?: never; header?: never; path: { subscription_id: string }; cookie?: never };
      requestBody?: never;
      responses: { 204: { headers: { [name: string]: unknown }; content?: never }; 403: Problem; 404: Problem };
    };
  };
};

export type InterviewPaths = Omit<paths, keyof ContractPaths> & ContractPaths;

export type InterviewsApi = ReturnType<typeof createClient<InterviewPaths>>;

export function createInterviewsApi(options: { baseUrl: string; fetch?: typeof fetch }): InterviewsApi {
  return createClient<InterviewPaths>({ baseUrl: options.baseUrl, fetch: options.fetch });
}

export function browserInterviewsApi(): InterviewsApi {
  return createInterviewsApi({ baseUrl: BROWSER_API_BASE });
}
