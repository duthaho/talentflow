"use client";

import { useRef, useState, type FormEvent, type ReactNode } from "react";

import { CONTROL_CLASS, FormProblem } from "@/components/pipeline/form-fields";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { settle } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";
import type { InterviewListItem, InterviewsApi } from "@/lib/interviews/contract";
import { COMMENTS_MAX, formatDateTime, RECOMMENDATION_LABELS, SCORES, validateFeedback, type FeedbackDraft } from "@/lib/interviews/format";

type Errors = Partial<Record<keyof FeedbackDraft, string>>;

const SCORE_HINTS: Record<number, string> = { 1: "Poor", 2: "Weak", 3: "Mixed", 4: "Good", 5: "Excellent" };

function ChoiceGroup({ name, legend, error, children }: { name: string; legend: string; error?: string; children: ReactNode }) {
  return (
    <fieldset className="grid gap-1.5" aria-describedby={error ? `${name}-error` : undefined} aria-invalid={error ? true : undefined}>
      <legend className="mb-1.5 text-sm font-medium">{legend}</legend>
      <div className="flex flex-wrap gap-2">{children}</div>
      {error && (
        <p id={`${name}-error`} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
}

function Choice({ name, value, label, hint }: { name: string; value: string; label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm has-checked:border-primary has-checked:bg-primary/10 has-focus-visible:ring-3 has-focus-visible:ring-ring/50">
      <input type="radio" name={name} value={value} className="accent-primary" aria-label={hint ? `${label} – ${hint}` : undefined} />
      {label}
    </label>
  );
}

export function FeedbackDialog({
  api,
  interview,
  onOpenChange,
  onSubmitted,
  onAlreadySubmitted,
}: {
  api: InterviewsApi;
  interview: InterviewListItem | null;
  onOpenChange: (open: boolean) => void;
  onSubmitted: (interview: InterviewListItem) => void;
  onAlreadySubmitted: (interview: InterviewListItem) => void;
}) {
  const [errors, setErrors] = useState<Errors>({});
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [length, setLength] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);

  function changeOpen(open: boolean) {
    if (!open) {
      setErrors({});
      setProblem(null);
      setLength(0);
    }
    onOpenChange(open);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!interview || submitting) return;
    const form = new FormData(event.currentTarget);
    const checked = validateFeedback({
      score: String(form.get("score") ?? ""),
      recommendation: String(form.get("recommendation") ?? ""),
      comments: String(form.get("comments") ?? ""),
    });
    setProblem(null);
    if (!checked.ok) {
      setErrors(checked.errors);
      const first = (["score", "recommendation", "comments"] as const).find((key) => checked.errors[key]);
      formRef.current?.querySelector<HTMLElement>(`[name="${first}"]`)?.focus();
      return;
    }
    setErrors({});
    setSubmitting(true);
    const result = await settle(
      api.POST("/v1/interviews/{interview_id}/feedback", { params: { path: { interview_id: interview.id } }, body: checked.body }),
    );
    setSubmitting(false);
    if (result.ok) {
      onSubmitted(interview);
      return;
    }
    if (result.problem.status === 409) onAlreadySubmitted(interview);
    setProblem(result.problem);
  }

  const alreadySubmitted = problem?.status === 409;

  return (
    <Dialog open={interview !== null} onOpenChange={changeOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Interview feedback</DialogTitle>
          <DialogDescription>
            {interview ? `${interview.candidate_name} · ${interview.requisition_title} · ${formatDateTime(interview.scheduled_at)}. ` : ""}
            You can submit feedback once; it cannot be edited afterwards.
          </DialogDescription>
        </DialogHeader>
        {alreadySubmitted ? (
          <div className="space-y-3">
            <p role="status" className="rounded-lg border p-3">
              Feedback for this interview was already submitted. Each interview takes one feedback.
            </p>
            <DialogFooter>
              <DialogClose asChild>
                <Button type="button">Got it</Button>
              </DialogClose>
            </DialogFooter>
          </div>
        ) : (
          <form ref={formRef} noValidate onSubmit={(event) => void submit(event)} className="grid gap-4">
            <ChoiceGroup name="score" legend="Score" error={errors.score}>
              {SCORES.map((score) => (
                <Choice key={score} name="score" value={String(score)} label={String(score)} hint={SCORE_HINTS[score]} />
              ))}
            </ChoiceGroup>
            <ChoiceGroup name="recommendation" legend="Recommendation" error={errors.recommendation}>
              {Object.entries(RECOMMENDATION_LABELS).map(([value, label]) => (
                <Choice key={value} name="recommendation" value={value} label={label} />
              ))}
            </ChoiceGroup>
            <div className="grid gap-1.5">
              <label htmlFor="feedback-comments" className="text-sm font-medium">
                Comments
              </label>
              <textarea
                id="feedback-comments"
                name="comments"
                rows={5}
                maxLength={COMMENTS_MAX}
                onChange={(event) => setLength(event.target.value.length)}
                className={`${CONTROL_CLASS} h-auto py-2`}
                aria-invalid={errors.comments ? true : undefined}
                aria-describedby={`feedback-comments-count${errors.comments ? " feedback-comments-error" : ""}`}
              />
              <div className="flex justify-between gap-2 text-xs">
                <span id="feedback-comments-error" className="text-destructive">
                  {errors.comments}
                </span>
                <span id="feedback-comments-count" className="text-muted-foreground tabular-nums">
                  {length}/{COMMENTS_MAX}
                </span>
              </div>
            </div>
            {problem && <FormProblem problem={problem} />}
            <DialogFooter>
              <DialogClose asChild>
                <Button type="button" variant="outline">
                  Cancel
                </Button>
              </DialogClose>
              <Button type="submit" disabled={submitting}>
                {submitting ? "Submitting…" : "Submit feedback"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
