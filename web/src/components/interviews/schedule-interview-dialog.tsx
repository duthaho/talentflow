"use client";

import { useEffect, useState, type FormEvent } from "react";

import { CONTROL_CLASS, Field, fieldError, FormProblem, TextField } from "@/components/pipeline/form-fields";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { settle, type ApiResult } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";
import type { CandidateCase, Interviewer, InterviewsApi } from "@/lib/interviews/contract";
import { localInputToIso } from "@/lib/interviews/format";

export const SCHEDULABLE_STAGES = ["screening", "interviewing"] as const;
const OPTIONS_LIMIT = 100;

type Options = { status: "loading" } | { status: "error"; problem: ProblemDetails } | { status: "ready"; candidates: CandidateCase[]; interviewers: Interviewer[] };

export type ScheduledInterview = { candidateName: string; interviewerLabel: string };

function fullName(candidate: CandidateCase): string {
  return `${candidate.first_name} ${candidate.last_name}`;
}

export function interviewerLabel(interviewer: Pick<Interviewer, "id" | "email">): string {
  return interviewer.email ?? `Interviewer ${interviewer.id.slice(0, 8)}`;
}

function firstFailure(results: ApiResult<unknown>[]): ProblemDetails | null {
  for (const result of results) if (!result.ok) return result.problem;
  return null;
}

async function loadOptions(api: InterviewsApi): Promise<Options> {
  const [interviewers, ...stages] = await Promise.all([
    settle(api.GET("/v1/interviewers")),
    ...SCHEDULABLE_STAGES.map((stage) => settle(api.GET("/v1/candidate-cases", { params: { query: { stage, limit: OPTIONS_LIMIT } } }))),
  ]);
  const problem = firstFailure([interviewers, ...stages]);
  if (problem || !interviewers.ok) return { status: "error", problem: problem! };
  const candidates = stages.flatMap((result) => (result.ok ? result.data.items : []));
  candidates.sort((a, b) => fullName(a).localeCompare(fullName(b)));
  return { status: "ready", candidates, interviewers: interviewers.data.items };
}

export function ScheduleInterviewDialog({
  api,
  open,
  onOpenChange,
  onScheduled,
}: {
  api: InterviewsApi;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onScheduled: (interview: ScheduledInterview) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Schedule interview</DialogTitle>
          <DialogDescription>The interviewer sees it under My interviews and in their calendar feed.</DialogDescription>
        </DialogHeader>
        <ScheduleForm api={api} onScheduled={onScheduled} />
      </DialogContent>
    </Dialog>
  );
}

function ScheduleForm({ api, onScheduled }: { api: InterviewsApi; onScheduled: (interview: ScheduledInterview) => void }) {
  const [options, setOptions] = useState<Options>({ status: "loading" });
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    void loadOptions(api).then((loaded) => current && setOptions(loaded));
    return () => {
      current = false;
    };
  }, [api, attempt]);

  function retry() {
    setOptions({ status: "loading" });
    setAttempt((count) => count + 1);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (options.status !== "ready") return;
    const form = new FormData(event.currentTarget);
    const candidateId = String(form.get("candidate_case_id") ?? "");
    const interviewerId = String(form.get("interviewer_id") ?? "");
    const scheduledAt = localInputToIso(String(form.get("scheduled_at") ?? ""));
    if (!scheduledAt) {
      setProblem({
        type: "about:blank",
        title: "Check the form",
        status: 422,
        errors: [{ pointer: "/body/scheduled_at", detail: "Pick a date and time." }],
      });
      return;
    }
    setSubmitting(true);
    setProblem(null);
    const result = await settle(
      api.POST("/v1/candidate-cases/{candidate_case_id}/interviews", {
        params: { path: { candidate_case_id: candidateId } },
        body: { interviewer_id: interviewerId, scheduled_at: scheduledAt },
      }),
    );
    setSubmitting(false);
    if (!result.ok) {
      setProblem(result.problem);
      return;
    }
    const candidate = options.candidates.find((item) => item.id === candidateId);
    const interviewer = options.interviewers.find((item) => item.id === interviewerId);
    onScheduled({
      candidateName: candidate ? fullName(candidate) : "the candidate",
      interviewerLabel: interviewer ? interviewerLabel(interviewer) : "the interviewer",
    });
  }

  return (
    <>
      {options.status === "loading" && (
        <div className="space-y-3" aria-busy="true" aria-label="Loading candidates and interviewers">
          <Skeleton className="h-8" />
          <Skeleton className="h-8" />
          <Skeleton className="h-8" />
        </div>
      )}
      {options.status === "error" && (
        <div className="space-y-3">
          <FormProblem problem={options.problem} />
          <Button type="button" variant="outline" size="sm" onClick={retry}>
            Retry
          </Button>
        </div>
      )}
      {options.status === "ready" && options.candidates.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-muted-foreground">
          No candidates are in the Screening or Interviewing stage. Move a candidate forward on the pipeline board first.
        </p>
      )}
      {options.status === "ready" && options.candidates.length > 0 && options.interviewers.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-muted-foreground">
          This tenant has no members with the Interviewer role yet. Ask a tenant admin to add one.
        </p>
      )}
      {options.status === "ready" && options.candidates.length > 0 && options.interviewers.length > 0 && (
        <form onSubmit={(event) => void submit(event)} className="grid gap-3">
          <Field id="interview-candidate" label="Candidate" error={fieldError(problem, "candidate_case_id")}>
            <select id="interview-candidate" name="candidate_case_id" required className={CONTROL_CLASS} defaultValue="">
              <option value="" disabled>
                Choose a candidate
              </option>
              {options.candidates.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {fullName(candidate)} ({candidate.email})
                </option>
              ))}
            </select>
          </Field>
          <Field id="interview-interviewer" label="Interviewer" error={fieldError(problem, "interviewer_id")}>
            <select id="interview-interviewer" name="interviewer_id" required className={CONTROL_CLASS} defaultValue="">
              <option value="" disabled>
                Choose an interviewer
              </option>
              {options.interviewers.map((interviewer) => (
                <option key={interviewer.id} value={interviewer.id}>
                  {interviewerLabel(interviewer)}
                </option>
              ))}
            </select>
          </Field>
          <TextField
            id="interview-scheduled-at"
            name="scheduled_at"
            label="Date and time (your local time)"
            type="datetime-local"
            required
            error={fieldError(problem, "scheduled_at")}
          />
          {problem && !problem.errors?.length && <FormProblem problem={problem} />}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Scheduling…" : "Schedule"}
            </Button>
          </DialogFooter>
        </form>
      )}
    </>
  );
}
