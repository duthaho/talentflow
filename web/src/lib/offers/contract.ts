import createClient from "openapi-fetch";

import { BROWSER_API_BASE } from "@/lib/api/client";
import type { components, paths } from "@/lib/api/schema";

// Hand-written from docs/specs/DUTH-115.md § Contract and docs/specs/DUTH-110.md route 1, until those
// routes ship and `make api-client` regenerates schema.ts. Delete this file then and point the
// imports at `components["schemas"]` / `paths`; the call sites stay the same.

export type OfferStatus = "pending_approval" | "approved" | "rejected";
export type OfferDecisionValue = "approved" | "rejected";

export type OfferSummary = {
  id: string;
  candidate_case_id: string;
  title: string;
  annual_salary: number;
  currency: string;
  status: OfferStatus;
  approval_step: number;
  awaiting_role: string | null;
  version: number;
  can_decide: boolean;
};

export type OfferDecision = {
  step: number;
  decision: OfferDecisionValue;
  actor_id: string;
  decided_at: string | null;
  reason: string | null;
};

export type OfferDetail = OfferSummary & { decisions: OfferDecision[] };

export type OfferPage = { items: OfferSummary[]; next_cursor: string | null; total: number };

export type CandidateCaseDetail = {
  id: string;
  requisition_id: string;
  first_name: string;
  last_name: string;
  email: string;
  stage: string;
  version: number;
  created_at: string;
};

export type ApproveOfferBody = { decision: OfferDecisionValue; expected_version: number; reason?: string | null };

type Json<T> = { headers: { [name: string]: unknown }; content: { "application/json": T } };
type Problem = Json<unknown>;
type NoParams = { query?: never; header?: never; path?: never; cookie?: never };
type Unused = { put?: never; delete?: never; options?: never; head?: never; patch?: never; trace?: never };

type ContractPaths = {
  "/v1/offers": Unused & {
    parameters: NoParams;
    get: {
      parameters: {
        query?: { awaiting?: "me"; candidate_case_id?: string; status?: OfferStatus; cursor?: string; limit?: number };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: { 200: Json<OfferPage>; 403: Problem; 422: Problem };
    };
    post?: never;
  };
  "/v1/offers/{offer_id}": Unused & {
    parameters: NoParams;
    get: {
      parameters: { query?: never; header?: never; path: { offer_id: string }; cookie?: never };
      requestBody?: never;
      responses: { 200: Json<OfferDetail>; 403: Problem; 404: Problem };
    };
    post?: never;
  };
  "/v1/offers/{offer_id}/approvals": Unused & {
    parameters: NoParams;
    get?: never;
    post: {
      parameters: { query?: never; header?: never; path: { offer_id: string }; cookie?: never };
      requestBody: { content: { "application/json": ApproveOfferBody } };
      responses: { 200: Json<components["schemas"]["OfferResponse"]>; 403: Problem; 409: Problem; 422: Problem };
    };
  };
  "/v1/candidate-cases/{candidate_case_id}": Unused & {
    parameters: NoParams;
    get: {
      parameters: { query?: never; header?: never; path: { candidate_case_id: string }; cookie?: never };
      requestBody?: never;
      responses: { 200: Json<CandidateCaseDetail>; 403: Problem; 404: Problem };
    };
    post?: never;
  };
};

export type OfferPaths = Omit<paths, keyof ContractPaths> & ContractPaths;

export type OffersApi = ReturnType<typeof createClient<OfferPaths>>;

export function createOffersApi(options: { baseUrl: string; fetch?: typeof fetch }): OffersApi {
  return createClient<OfferPaths>({ baseUrl: options.baseUrl, fetch: options.fetch });
}

export function browserOffersApi(): OffersApi {
  return createOffersApi({ baseUrl: BROWSER_API_BASE });
}
