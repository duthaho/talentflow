import { Lock, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { describeProblem, type ProblemDetails } from "@/lib/api/problem";

export function Panel({
  id,
  title,
  description,
  busy = false,
  actions,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  busy?: boolean;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const headingId = `${id}-heading`;
  return (
    <section aria-labelledby={headingId} aria-busy={busy} data-panel={id} className="space-y-3 rounded-xl border bg-card p-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={headingId} className="text-base font-medium">
            {title}
          </h2>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function NoAccess({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
      <Lock aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

export function PanelProblem({ problem, what, onRetry }: { problem: ProblemDetails; what: string; onRetry: () => void }) {
  const view = describeProblem(problem);
  if (view.kind === "forbidden") return <NoAccess>Your role can&apos;t view {what}. Ask a tenant admin if you need access.</NoAccess>;
  return (
    <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 p-3 text-sm">
      <p className="font-medium text-destructive">{view.title}</p>
      <p className="text-muted-foreground">{view.description}</p>
      {view.correlationId && <p className="text-xs text-muted-foreground">Reference: {view.correlationId}</p>}
      <Button size="sm" variant="outline" onClick={onRetry}>
        <RefreshCw aria-hidden />
        Retry
      </Button>
    </div>
  );
}
