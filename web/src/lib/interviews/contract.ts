import { browserApi, createApiClient, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type InterviewListItem = components["schemas"]["InterviewListItem"];
export type Interviewer = components["schemas"]["InterviewerItem"];
export type CandidateCase = components["schemas"]["CandidateCaseResponse"];
export type Recommendation = "strong_hire" | "hire" | "no_hire" | "strong_no_hire";

export type CalendarSubscription = components["schemas"]["CalendarSubscriptionResponse"];
export type CalendarSubscriptionSummary = components["schemas"]["CalendarSubscriptionSummary"];

export type InterviewsApi = ApiClient;

export function createInterviewsApi(options: { baseUrl: string; fetch?: typeof fetch }): InterviewsApi {
  return createApiClient(options);
}

export function browserInterviewsApi(): InterviewsApi {
  return browserApi();
}
