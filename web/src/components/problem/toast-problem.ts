"use client";

import { toast } from "sonner";

import { describeProblem, type ProblemDetails } from "@/lib/api/problem";

export function toastProblem(problem: ProblemDetails): string | number {
  const view = describeProblem(problem);
  const reference = view.correlationId ? ` Reference: ${view.correlationId}` : "";
  return toast.error(view.title, {
    id: view.correlationId,
    description: `${view.description}${reference}`,
    action:
      view.kind === "unauthenticated"
        ? {
            label: "Sign in",
            onClick: () =>
              // /auth/login is a route handler that redirects to Keycloak, so it needs a full page load.
              // eslint-disable-next-line @next/next/no-location-assign-relative-destination
              window.location.assign(`/auth/login?returnTo=${encodeURIComponent(window.location.pathname)}`),
          }
        : undefined,
  });
}
