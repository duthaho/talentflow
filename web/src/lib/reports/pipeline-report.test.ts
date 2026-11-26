import { describe, expect, it } from "vitest";

import { STAGES } from "@/lib/pipeline/stages";

import { interviewActivity, isEmptyReport, offerStatuses, stageDistribution, type PipelineReport } from "./pipeline-report";

function report(overrides: Partial<PipelineReport> = {}): PipelineReport {
  return {
    candidates: { total: 3, by_stage: { screening: 2, applied: 1 } },
    offers: { total: 1, by_status: { approved: 1 } },
    interviews: { scheduled_total: 2, feedback_submitted_total: 1 },
    ...overrides,
  };
}

describe("stageDistribution", () => {
  it("lists every stage in pipeline order, filling missing stages with zero", () => {
    const data = stageDistribution(report());
    expect(data.map((datum) => datum.key)).toEqual([...STAGES]);
    expect(data.find((datum) => datum.key === "applied")).toEqual({ key: "applied", label: "Applied", value: 1 });
    expect(data.find((datum) => datum.key === "hired")?.value).toBe(0);
  });

  it("keeps a stage the web app does not know yet, after the known ones", () => {
    const data = stageDistribution(report({ candidates: { total: 1, by_stage: { on_hold: 1 } } }));
    expect(data.at(-1)).toEqual({ key: "on_hold", label: "On hold", value: 1 });
  });
});

describe("offerStatuses", () => {
  it("lists the offer statuses in approval order", () => {
    expect(offerStatuses(report())).toEqual([
      { key: "pending_approval", label: "Pending approval", value: 0 },
      { key: "approved", label: "Approved", value: 1 },
      { key: "rejected", label: "Rejected", value: 0 },
    ]);
  });
});

describe("interviewActivity", () => {
  it("compares scheduled interviews with submitted feedback", () => {
    expect(interviewActivity(report()).map((datum) => datum.value)).toEqual([2, 1]);
  });
});

describe("isEmptyReport", () => {
  it("is empty only when there are no candidates, offers or interviews", () => {
    const empty = report({
      candidates: { total: 0, by_stage: {} },
      offers: { total: 0, by_status: {} },
      interviews: { scheduled_total: 0, feedback_submitted_total: 0 },
    });
    expect(isEmptyReport(empty)).toBe(true);
    expect(isEmptyReport({ ...empty, interviews: { scheduled_total: 1, feedback_submitted_total: 0 } })).toBe(false);
  });
});
