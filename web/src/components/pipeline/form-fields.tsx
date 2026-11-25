import type { ComponentProps, ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { describeProblem, type ProblemDetails } from "@/lib/api/problem";

export const CONTROL_CLASS =
  "h-8 w-full min-w-0 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 aria-invalid:border-destructive";

export function fieldError(problem: ProblemDetails | null, name: string): string | undefined {
  return problem?.errors?.find((error) => error.pointer.split("/").at(-1) === name)?.detail;
}

export function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {error && (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

export function TextField({
  id,
  label,
  error,
  ...input
}: { id: string; label: string; error?: string } & Omit<ComponentProps<"input">, "id">) {
  return (
    <Field id={id} label={label} error={error}>
      <input
        id={id}
        className={CONTROL_CLASS}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        {...input}
      />
    </Field>
  );
}

export function FormProblem({ problem }: { problem: ProblemDetails }) {
  const view = describeProblem(problem);
  return (
    <Alert variant="destructive">
      <AlertTitle>{view.title}</AlertTitle>
      <AlertDescription>
        {view.description}
        {view.correlationId && <span className="block">Reference: {view.correlationId}</span>}
      </AlertDescription>
    </Alert>
  );
}
