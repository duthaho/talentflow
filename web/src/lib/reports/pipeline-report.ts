import type { components } from "@/lib/api/schema";
import { STAGES, STAGE_LABELS, isStage } from "@/lib/pipeline/stages";

export type PipelineReport = components["schemas"]["PipelineReportResponse"];

export type ChartDatum = { key: string; label: string; value: number };

const OFFER_STATUSES = ["pending_approval", "approved", "rejected"] as const;

const OFFER_STATUS_LABELS: Record<(typeof OFFER_STATUSES)[number], string> = {
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
};

function humanize(key: string): string {
  const words = key.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Known keys keep their domain order and show up as zero, so the charts stay comparable over time;
// a key the web app does not know yet is still shown rather than silently dropped.
function ordered(counts: Record<string, number>, known: readonly string[], label: (key: string) => string): ChartDatum[] {
  const extra = Object.keys(counts)
    .filter((key) => !known.includes(key))
    .sort();
  return [...known, ...extra].map((key) => ({ key, label: label(key), value: counts[key] ?? 0 }));
}

export function stageDistribution(report: PipelineReport): ChartDatum[] {
  return ordered(report.candidates.by_stage, STAGES, (key) => (isStage(key) ? STAGE_LABELS[key] : humanize(key)));
}

export function offerStatuses(report: PipelineReport): ChartDatum[] {
  return ordered(report.offers.by_status, OFFER_STATUSES, (key) =>
    key in OFFER_STATUS_LABELS ? OFFER_STATUS_LABELS[key as keyof typeof OFFER_STATUS_LABELS] : humanize(key),
  );
}

export function interviewActivity(report: PipelineReport): ChartDatum[] {
  return [
    { key: "scheduled", label: "Interviews scheduled", value: report.interviews.scheduled_total },
    { key: "feedback_submitted", label: "Feedback submitted", value: report.interviews.feedback_submitted_total },
  ];
}

export function isEmptyReport(report: PipelineReport): boolean {
  return report.candidates.total === 0 && report.offers.total === 0 && report.interviews.scheduled_total === 0;
}
