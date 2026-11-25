import { LockKeyhole, SearchX, ServerCrash, ShieldAlert, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { describeProblem, type ProblemDetails, type ProblemPresentation } from "@/lib/api/problem";

const ICONS: Record<ProblemPresentation["kind"], typeof TriangleAlert> = {
  unauthenticated: LockKeyhole,
  forbidden: ShieldAlert,
  "not-found": SearchX,
  conflict: TriangleAlert,
  validation: TriangleAlert,
  "rate-limited": TriangleAlert,
  unavailable: ServerCrash,
  error: ServerCrash,
};

export function ProblemView({ problem, retryHref }: { problem: ProblemDetails; retryHref?: string }) {
  const view = describeProblem(problem);
  const Icon = ICONS[view.kind];
  return (
    <Card role="alert" aria-live="polite" className="mx-auto w-full max-w-xl" data-problem-kind={view.kind}>
      <CardHeader>
        <Icon aria-hidden className="mb-2 size-6 text-muted-foreground" />
        <CardTitle role="heading" aria-level={2}>{view.title}</CardTitle>
        <CardDescription>{view.description}</CardDescription>
      </CardHeader>
      {(view.fieldErrors.length > 0 || view.correlationId) && (
        <CardContent className="space-y-2 text-sm">
          {view.fieldErrors.length > 0 && (
            <ul className="list-disc pl-5">
              {view.fieldErrors.map((error) => (
                <li key={error.pointer}>
                  <code>{error.pointer}</code>: {error.detail}
                </li>
              ))}
            </ul>
          )}
          {view.correlationId && (
            <p className="text-muted-foreground">
              Reference: <code className="select-all">{view.correlationId}</code>
            </p>
          )}
        </CardContent>
      )}
      <CardFooter className="gap-2">
        {view.kind === "unauthenticated" ? (
          <Button asChild>
            <a href="/auth/login">Sign in</a>
          </Button>
        ) : (
          <>
            {view.retryable && retryHref && (
              <Button asChild>
                <a href={retryHref}>Try again</a>
              </Button>
            )}
            <Button asChild variant="outline">
              <Link href="/">Back to overview</Link>
            </Button>
          </>
        )}
      </CardFooter>
    </Card>
  );
}
