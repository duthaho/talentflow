"use client";

import { useEffect, useState, type FormEvent } from "react";

import { CandidatePicker, findCandidates, fullName, type CandidateResults } from "@/components/interviews/candidate-picker";
import { CONTROL_CLASS, Field, fieldError, FormProblem, TextField } from "@/components/pipeline/form-fields";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { settle } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";
import type { CandidateCase, Interviewer, InterviewsApi } from "@/lib/interviews/contract";
import { localInputToIso } from "@/lib/interviews/format";

type Options = { status: "loading" } | { status: "error"; problem: ProblemDetails } | { status: "ready"; candidates: CandidateResults; interviewers: Interviewer[] };

export type ScheduledInterview = { candidateName: string; interviewerLabel: string };

export function interviewerLabel(interviewer: Pick<Interviewer, "id" | "email">): string {
  return interviewer.email ?? `Interviewer ${interviewer.id.slice(0, 8)}`;
}

async function loadOptions(api: InterviewsApi): Promise<Options> {
  const [interviewers, candidates] = await Promise.all([settle(api.GET("/v1/interviewers")), findCandidates(api)]);
  if (!interviewers.ok) return { status: "error", problem: interviewers.problem };
  if (!candidates.ok) return { status: "error", problem: candidates.problem };
  return { status: "ready", candidates: candidates.data, interviewers: interviewers.data.items };
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
      <DialogContent
        onEscapeKeyDown={(event) => {
          const target = event.target;
          if (target instanceof HTMLInputElement && target.dataset.clearOnEscape !== undefined && target.value) event.preventDefault();
        }}
      >
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
  const [candidate, setCandidate] = useState<CandidateCase | null>(null);
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
    const interviewerId = String(form.get("interviewer_id") ?? "");
    const scheduledAt = localInputToIso(String(form.get("scheduled_at") ?? ""));
    const errors = [
      ...(candidate ? [] : [{ pointer: "/body/candidate_case_id", detail: "Choose a candidate." }]),
      ...(scheduledAt ? [] : [{ pointer: "/body/scheduled_at", detail: "Pick a date and time." }]),
    ];
    if (!candidate || !scheduledAt) {
      setProblem({ type: "about:blank", title: "Check the form", status: 422, errors });
      return;
    }
    setSubmitting(true);
    setProblem(null);
    const result = await settle(
      api.POST("/v1/candidate-cases/{candidate_case_id}/interviews", {
        params: { path: { candidate_case_id: candidate.id } },
        body: { interviewer_id: interviewerId, scheduled_at: scheduledAt },
      }),
    );
    setSubmitting(false);
    if (!result.ok) {
      setProblem(result.problem);
      return;
    }
    const interviewer = options.interviewers.find((item) => item.id === interviewerId);
    onScheduled({
      candidateName: fullName(candidate),
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
      {options.status === "ready" && options.candidates.total === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-muted-foreground">
          No candidates are in the Screening or Interviewing stage. Move a candidate forward on the pipeline board first.
        </p>
      )}
      {options.status === "ready" && options.candidates.total > 0 && options.interviewers.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-muted-foreground">
          This tenant has no members with the Interviewer role yet. Ask a tenant admin to add one.
        </p>
      )}
      {options.status === "ready" && options.candidates.total > 0 && options.interviewers.length > 0 && (
        <form onSubmit={(event) => void submit(event)} className="grid gap-3">
          <CandidatePicker
            api={api}
            initial={options.candidates}
            selected={candidate}
            onSelect={setCandidate}
            error={fieldError(problem, "candidate_case_id")}
          />
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
