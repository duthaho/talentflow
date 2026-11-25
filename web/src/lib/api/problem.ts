export const PROBLEM_TYPE_BASE = "https://github.com/duthaho/talentflow/blob/main/docs/api-errors.md#";

export type ProblemDetails = {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  correlation_id?: string;
  errors?: { pointer: string; detail: string }[];
  current_version?: number;
};

export type ProblemPresentation = {
  kind: "unauthenticated" | "forbidden" | "not-found" | "conflict" | "validation" | "rate-limited" | "unavailable" | "error";
  title: string;
  description: string;
  fieldErrors: { pointer: string; detail: string }[];
  correlationId?: string;
  retryable: boolean;
};

export function isProblem(value: unknown): value is ProblemDetails {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.type === "string" && typeof candidate.title === "string" && typeof candidate.status === "number";
}

export function fallbackProblem(status: number, detail?: string): ProblemDetails {
  return {
    type: "about:blank",
    title: status >= 500 || status === 0 ? "Service error" : "Request failed",
    status,
    detail: detail ?? (status === 0 ? "The TalentFlow API could not be reached." : `The API responded with HTTP ${status}.`),
  };
}

export function toProblem(status: number, body: unknown): ProblemDetails {
  return isProblem(body) ? body : fallbackProblem(status);
}

const KIND_BY_SLUG: Record<string, ProblemPresentation["kind"]> = {
  unauthorized: "unauthenticated",
  forbidden: "forbidden",
  "not-found": "not-found",
  conflict: "conflict",
  "version-conflict": "conflict",
  "validation-error": "validation",
  "rate-limited": "rate-limited",
  "service-unavailable": "unavailable",
  "internal-error": "error",
};

const KIND_BY_STATUS: Record<number, ProblemPresentation["kind"]> = {
  401: "unauthenticated",
  403: "forbidden",
  404: "not-found",
  409: "conflict",
  412: "conflict",
  422: "validation",
  429: "rate-limited",
  503: "unavailable",
};

const TITLES: Record<ProblemPresentation["kind"], string> = {
  unauthenticated: "Your session has ended",
  forbidden: "You don't have access",
  "not-found": "Not found",
  conflict: "Someone else changed this",
  validation: "Check the highlighted fields",
  "rate-limited": "Too many requests",
  unavailable: "Service temporarily unavailable",
  error: "Something went wrong",
};

function kindOf(problem: ProblemDetails): ProblemPresentation["kind"] {
  if (problem.type.startsWith(PROBLEM_TYPE_BASE)) {
    const slug = problem.type.slice(PROBLEM_TYPE_BASE.length);
    if (KIND_BY_SLUG[slug]) return KIND_BY_SLUG[slug];
  }
  return KIND_BY_STATUS[problem.status] ?? "error";
}

export function describeProblem(problem: ProblemDetails): ProblemPresentation {
  const kind = kindOf(problem);
  const description =
    kind === "error"
      ? "The request failed unexpectedly. Try again, and quote the reference below if it keeps happening."
      : kind === "unauthenticated"
        ? "Sign in again to continue."
        : problem.detail || problem.title;
  return {
    kind,
    title: TITLES[kind],
    description,
    fieldErrors: problem.errors ?? [],
    correlationId: problem.correlation_id,
    retryable: kind === "rate-limited" || kind === "unavailable" || kind === "error",
  };
}
