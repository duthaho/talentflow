import type { Recommendation } from "./contract";

export const COMMENTS_MAX = 5000;

export const SCORES = [1, 2, 3, 4, 5] as const;

export const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  strong_hire: "Strong hire",
  hire: "Hire",
  no_hire: "No hire",
  strong_no_hire: "Strong no hire",
};

export function isRecommendation(value: string): value is Recommendation {
  return value in RECOMMENDATION_LABELS;
}

export function formatDateTime(value: string, timeZone?: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en", { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone, timeZoneName: "short" }).format(date);
}

export function formatDate(value: string, timeZone?: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeZone }).format(date);
}

// <input type="datetime-local"> yields wall-clock time without an offset; the API needs an instant.
export function localInputToIso(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export type FeedbackDraft = { score: string; recommendation: string; comments: string };
export type FeedbackBody = { score: number; recommendation: Recommendation; comments: string };

export function validateFeedback(draft: FeedbackDraft): { ok: true; body: FeedbackBody } | { ok: false; errors: Partial<Record<keyof FeedbackDraft, string>> } {
  const errors: Partial<Record<keyof FeedbackDraft, string>> = {};
  const score = Number(draft.score);
  if (!SCORES.includes(score as (typeof SCORES)[number])) errors.score = "Choose a score from 1 to 5.";
  if (!isRecommendation(draft.recommendation)) errors.recommendation = "Choose a recommendation.";
  const comments = draft.comments.trim();
  if (comments.length === 0) errors.comments = "Write a short justification for your score.";
  else if (comments.length > COMMENTS_MAX) errors.comments = `Keep comments to ${COMMENTS_MAX} characters or fewer.`;
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return { ok: true, body: { score, recommendation: draft.recommendation as Recommendation, comments } };
}
