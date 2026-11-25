// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import type { PipelineReport } from "@/lib/reports/pipeline-report";

import { PipelineReportView } from "./pipeline-report-view";

const REPORT: PipelineReport = {
  candidates: { total: 5, by_stage: { applied: 1, interviewing: 4 } },
  offers: { total: 2, by_status: { pending_approval: 1, approved: 1 } },
  interviews: { scheduled_total: 4, feedback_submitted_total: 3 },
};

function chart(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

function row(region: HTMLElement, label: string): HTMLElement {
  return within(region).getByRole("rowheader", { name: label }).closest("tr")!;
}

describe("PipelineReportView", () => {
  it("renders the stage, offer and interview charts with their counts", () => {
    render(<PipelineReportView result={{ ok: true, data: REPORT }} />);

    const stages = chart("Candidates by stage");
    expect(within(stages).getByRole("table", { name: "Candidate cases by pipeline stage" })).toBeInTheDocument();
    expect(row(stages, "Interviewing")).toHaveTextContent("4");
    expect(row(stages, "Hired")).toHaveTextContent("0");
    expect(within(stages).getByText("5 candidate cases in total.")).toBeInTheDocument();

    expect(row(chart("Offers by status"), "Pending approval")).toHaveTextContent("1");

    const interviews = chart("Interviews and feedback");
    expect(row(interviews, "Interviews scheduled")).toHaveTextContent("4");
    expect(row(interviews, "Feedback submitted")).toHaveTextContent("3");
    expect(within(interviews).getByText(/75% of scheduled interviews/)).toBeInTheDocument();
  });

  it("scales bars against the largest value in each chart", () => {
    render(<PipelineReportView result={{ ok: true, data: REPORT }} />);
    const stages = chart("Candidates by stage");
    expect(within(row(stages, "Interviewing")).getByTestId("bar")).toHaveStyle({ width: "100%" });
    expect(within(row(stages, "Applied")).getByTestId("bar")).toHaveStyle({ width: "25%" });
  });

  it("shows an empty state instead of blank charts when the tenant has no activity", () => {
    render(
      <PipelineReportView
        result={{
          ok: true,
          data: {
            candidates: { total: 0, by_stage: {} },
            offers: { total: 0, by_status: {} },
            interviews: { scheduled_total: 0, feedback_submitted_total: 0 },
          },
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: "No pipeline activity yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to candidates" })).toHaveAttribute("href", "/candidates");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows the problem with a retry when the report cannot be loaded", () => {
    render(
      <PipelineReportView
        result={{ ok: false, problem: { type: "about:blank", title: "Service error", status: 503, correlation_id: "corr-1" } }}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("corr-1");
    expect(within(alert).getByRole("link", { name: "Try again" })).toHaveAttribute("href", "/reports");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a forbidden problem when the API denies report:read", () => {
    render(
      <PipelineReportView
        result={{
          ok: false,
          problem: { type: `${PROBLEM_TYPE_BASE}forbidden`, title: "Forbidden", status: 403, detail: "Missing report:read" },
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveAttribute("data-problem-kind", "forbidden");
  });
});
