"use client";

import { BriefcaseBusiness, UserPlus } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { settle, type ApiClient, type ApiResult } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";
import type { components } from "@/lib/api/schema";
import type { Candidate } from "@/lib/pipeline/board-state";

import { CONTROL_CLASS, Field, fieldError, FormProblem, TextField } from "./form-fields";

export type RequisitionOption = { id: string; label: string };
type Requisition = components["schemas"]["RequisitionResponse"];
type DialogState = { open: boolean; onOpenChange: (open: boolean) => void; problem: ProblemDetails | null; submitting: boolean };

function useSubmit<T>(onSuccess: (data: T) => void) {
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (next) setProblem(null);
  }

  async function submit(call: Promise<ApiResult<T>>) {
    setSubmitting(true);
    const result = await call;
    setSubmitting(false);
    if (result.ok) {
      setOpen(false);
      onSuccess(result.data);
    } else {
      setProblem(result.problem);
    }
  }

  return { open, onOpenChange, problem, submitting, submit };
}

function FormDialog({
  trigger,
  title,
  description,
  submitLabel,
  state,
  disabled,
  onSubmit,
  children,
}: {
  trigger: ReactNode;
  title: string;
  description: string;
  submitLabel: string;
  state: DialogState;
  disabled?: boolean;
  onSubmit: (form: FormData) => Promise<void>;
  children: ReactNode;
}) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onSubmit(new FormData(event.currentTarget));
  }

  return (
    <Dialog open={state.open} onOpenChange={state.onOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-3">
          {children}
          {state.problem && !state.problem.errors?.length && <FormProblem problem={state.problem} />}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={disabled || state.submitting}>
              {state.submitting ? "Saving…" : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function text(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

export function NewCandidateDialog({
  api,
  requisitions,
  defaultRequisitionId,
  onCreated,
}: {
  api: ApiClient;
  requisitions: RequisitionOption[];
  defaultRequisitionId: string | null;
  onCreated: (candidate: Candidate) => void;
}) {
  const state = useSubmit<Candidate>(onCreated);
  const noRequisitions = requisitions.length === 0;

  return (
    <FormDialog
      trigger={
        <Button>
          <UserPlus aria-hidden />
          New candidate
        </Button>
      }
      title="New candidate"
      description="The candidate starts in Applied."
      submitLabel="Create candidate"
      state={state}
      disabled={noRequisitions}
      onSubmit={(form) =>
        state.submit(
          settle(
            api.POST("/v1/candidate-cases", {
              body: {
                requisition_id: text(form, "requisition_id"),
                first_name: text(form, "first_name"),
                last_name: text(form, "last_name"),
                email: text(form, "email"),
              },
            }),
          ),
        )
      }
    >
      <Field id="candidate-requisition" label="Requisition" error={fieldError(state.problem, "requisition_id")}>
        <select
          id="candidate-requisition"
          name="requisition_id"
          required
          defaultValue={defaultRequisitionId ?? requisitions[0]?.id}
          className={CONTROL_CLASS}
          disabled={noRequisitions}
        >
          {requisitions.map((requisition) => (
            <option key={requisition.id} value={requisition.id}>
              {requisition.label}
            </option>
          ))}
        </select>
      </Field>
      {noRequisitions && <p className="text-xs text-muted-foreground">Create a requisition first.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField id="candidate-first-name" name="first_name" label="First name" required maxLength={100} autoComplete="off" error={fieldError(state.problem, "first_name")} />
        <TextField id="candidate-last-name" name="last_name" label="Last name" required maxLength={100} autoComplete="off" error={fieldError(state.problem, "last_name")} />
      </div>
      <TextField id="candidate-email" name="email" type="email" label="Email" required maxLength={320} autoComplete="off" error={fieldError(state.problem, "email")} />
    </FormDialog>
  );
}

export function NewRequisitionDialog({ api, onCreated }: { api: ApiClient; onCreated: (requisition: Requisition) => void }) {
  const state = useSubmit<Requisition>(onCreated);

  return (
    <FormDialog
      trigger={
        <Button variant="outline">
          <BriefcaseBusiness aria-hidden />
          New requisition
        </Button>
      }
      title="New requisition"
      description="Open a role to collect candidates against."
      submitLabel="Create requisition"
      state={state}
      onSubmit={(form) =>
        state.submit(settle(api.POST("/v1/requisitions", { body: { title: text(form, "title"), department: text(form, "department") } })))
      }
    >
      <TextField id="requisition-title" name="title" label="Title" required minLength={2} maxLength={160} error={fieldError(state.problem, "title")} />
      <TextField id="requisition-department" name="department" label="Department" required minLength={2} maxLength={120} error={fieldError(state.problem, "department")} />
    </FormDialog>
  );
}
