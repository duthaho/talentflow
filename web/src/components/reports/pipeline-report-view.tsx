import type { ReactNode } from "react";
import { ChartNoAxesColumn } from "lucide-react";
import Link from "next/link";

import { ProblemView } from "@/components/problem/problem-view";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import type { ApiResult } from "@/lib/api/client";
import {
  interviewActivity,
  isEmptyReport,
  offerStatuses,
  stageDistribution,
  type PipelineReport,
} from "@/lib/reports/pipeline-report";

import { BarChart } from "./bar-chart";

function ChartCard({ id, title, description, children }: { id: string; title: string; description: string; children: ReactNode }) {
  return (
    <Card aria-labelledby={`${id}-title`} role="region">
      <CardHeader>
        <CardTitle id={`${id}-title`} role="heading" aria-level={2}>
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function EmptyReport() {
  return (
    <Card className="max-w-xl border-dashed" data-testid="report-empty">
      <CardHeader>
        <ChartNoAxesColumn aria-hidden className="mb-2 size-6 text-muted-foreground" />
        <CardTitle role="heading" aria-level={2}>
          No pipeline activity yet
        </CardTitle>
        <CardDescription>
          Charts appear once your tenant has candidates, interviews or offers. Add a candidate to the pipeline to get
          started.
        </CardDescription>
      </CardHeader>
      <CardFooter>
        <Button asChild variant="outline">
          <Link href="/candidates">Go to candidates</Link>
        </Button>
      </CardFooter>
    </Card>
  );
}

function percent(part: number, whole: number): string {
  return whole === 0 ? "—" : `${Math.round((part / whole) * 100)}%`;
}

export function PipelineReportView({ result }: { result: ApiResult<PipelineReport> }) {
  if (!result.ok) return <ProblemView problem={result.problem} retryHref="/reports" />;
  const report = result.data;
  if (isEmptyReport(report)) return <EmptyReport />;
  const { scheduled_total, feedback_submitted_total } = report.interviews;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard
        id="stages"
        title="Candidates by stage"
        description={`${report.candidates.total} candidate cases in total.`}
      >
        <BarChart caption="Candidate cases by pipeline stage" data={stageDistribution(report)} unit="Candidates" />
      </ChartCard>
      <ChartCard id="offers" title="Offers by status" description={`${report.offers.total} offers in total.`}>
        <BarChart caption="Offers by approval status" data={offerStatuses(report)} unit="Offers" />
      </ChartCard>
      <ChartCard
        id="interviews"
        title="Interviews and feedback"
        description={`Feedback submitted for ${percent(feedback_submitted_total, scheduled_total)} of scheduled interviews.`}
      >
        <BarChart caption="Scheduled interviews and submitted feedback" data={interviewActivity(report)} unit="Count" />
      </ChartCard>
    </div>
  );
}
