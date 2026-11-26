"use client";

import { useState, type FormEvent } from "react";

import { fieldError, FormProblem, TextField } from "@/components/pipeline/form-fields";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { settle } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";
import type { OffersApi } from "@/lib/offers/contract";

export type OfferCandidate = { id: string; name: string };

export function CreateOfferDialog({
  api,
  candidate,
  onOpenChange,
  onCreated,
}: {
  api: OffersApi;
  candidate: OfferCandidate | null;
  onOpenChange: (open: boolean) => void;
  onCreated: (offerId: string) => void;
}) {
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function changeOpen(open: boolean) {
    if (!open) setProblem(null);
    onOpenChange(open);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!candidate) return;
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setProblem(null);
    const result = await settle(
      api.POST("/v1/candidate-cases/{candidate_case_id}/offers", {
        params: { path: { candidate_case_id: candidate.id } },
        body: {
          title: String(form.get("title") ?? "").trim(),
          annual_salary: Number(form.get("annual_salary")),
          currency: String(form.get("currency") ?? "").trim().toUpperCase(),
        },
      }),
    );
    setSubmitting(false);
    if (result.ok) {
      onCreated(result.data.id);
    } else {
      setProblem(result.problem);
    }
  }

  return (
    <Dialog open={candidate !== null} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New offer</DialogTitle>
          <DialogDescription>
            {candidate ? `For ${candidate.name}. ` : ""}The offer goes to the hiring manager, then the tenant admin, for approval.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)} className="grid gap-3">
          <TextField id="offer-title" name="title" label="Job title" required minLength={2} maxLength={160} autoComplete="off" error={fieldError(problem, "title")} />
          <div className="grid gap-3 sm:grid-cols-[1fr_7rem]">
            <TextField
              id="offer-salary"
              name="annual_salary"
              label="Annual salary"
              type="number"
              inputMode="numeric"
              required
              min={1}
              step={1}
              error={fieldError(problem, "annual_salary")}
            />
            <TextField
              id="offer-currency"
              name="currency"
              label="Currency"
              required
              defaultValue="EUR"
              pattern="[A-Za-z]{3}"
              maxLength={3}
              title="Three-letter ISO 4217 code, e.g. EUR"
              autoComplete="off"
              error={fieldError(problem, "currency")}
            />
          </div>
          {problem && !problem.errors?.length && <FormProblem problem={problem} />}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Saving…" : "Create offer"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
