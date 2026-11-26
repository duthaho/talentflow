"use client";

import { Check, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { FormProblem } from "@/components/pipeline/form-fields";
import { toastProblem } from "@/components/problem/toast-problem";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { settle } from "@/lib/api/client";
import { ifMatch, isStaleVersion } from "@/lib/api/precondition";
import { describeProblem, type ProblemDetails } from "@/lib/api/problem";
import type { OfferDecision, OfferDecisionValue, OfferDetail, OffersApi } from "@/lib/offers/contract";
import { formatDecidedAt, formatSalary, REASON_MAX, reasonError, reasonPayload, roleLabel } from "@/lib/offers/format";

import { OfferStatusBadge } from "./offer-status-badge";

type Load = { status: "loading" } | { status: "ready"; offer: OfferDetail } | { status: "error"; problem: ProblemDetails };
type Loaded = Exclude<Load, { status: "loading" }> & { id: string };

export function actorLabel(actorId: string, currentUserId: string): string {
  return actorId === currentUserId ? "You" : `User ${actorId.slice(0, 8)}`;
}

export function OfferSheet({
  api,
  offerId,
  currentUserId,
  candidateName,
  onClose,
  onDecided,
}: {
  api: OffersApi;
  offerId: string | null;
  currentUserId: string;
  candidateName: (candidateCaseId: string) => string;
  onClose: () => void;
  onDecided: (offer: OfferDetail) => void;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [conflictFor, setConflictFor] = useState<string | null>(null);
  const generation = useRef(0);

  const fetchDetail = useCallback(
    async (id: string) => {
      const run = ++generation.current;
      const result = await settle(api.GET("/v1/offers/{offer_id}", { params: { path: { offer_id: id } } }));
      if (run !== generation.current) return null;
      setLoaded(result.ok ? { id, status: "ready", offer: result.data } : { id, status: "error", problem: result.problem });
      return result.ok ? result.data : null;
    },
    [api],
  );

  useEffect(() => {
    if (offerId) void fetchDetail(offerId);
  }, [offerId, fetchDetail]);

  const load: Load = loaded && loaded.id === offerId ? loaded : { status: "loading" };
  const offer = load.status === "ready" ? load.offer : null;

  function reload(id: string) {
    setLoaded(null);
    return fetchDetail(id);
  }

  async function refreshAfterDecision(id: string, changedElsewhere: boolean) {
    setConflictFor(changedElsewhere ? id : null);
    setLoaded(null);
    const fresh = await fetchDetail(id);
    if (fresh) onDecided(fresh);
  }

  return (
    <Sheet open={offerId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-md">
        <SheetHeader className="border-b">
          <SheetTitle>{offer ? offer.title : "Offer"}</SheetTitle>
          <SheetDescription>{offer ? candidateName(offer.candidate_case_id) : "Loading offer details."}</SheetDescription>
        </SheetHeader>
        <div className="space-y-6 p-4" aria-busy={load.status === "loading"}>
          {load.status === "loading" && (
            <>
              <Skeleton className="h-16" />
              <Skeleton className="h-24" />
            </>
          )}
          {load.status === "error" && (
            <div role="alert" className="space-y-2 text-sm">
              <p className="font-medium">{describeProblem(load.problem).title}</p>
              <p className="text-muted-foreground">{describeProblem(load.problem).description}</p>
              {offerId && (
                <Button size="sm" variant="outline" onClick={() => void reload(offerId)}>
                  <RefreshCw aria-hidden />
                  Retry
                </Button>
              )}
            </div>
          )}
          {conflictFor !== null && conflictFor === offerId && (
            <Alert>
              <AlertTitle>Changed by someone else</AlertTitle>
              <AlertDescription>
                This offer changed after you opened it, so your decision was not recorded. Review the latest version below.
              </AlertDescription>
            </Alert>
          )}
          {offer && (
            <>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <OfferStatusBadge status={offer.status} />
                </dd>
                <dt className="text-muted-foreground">Annual salary</dt>
                <dd className="font-medium tabular-nums">{formatSalary(offer.annual_salary, offer.currency)}</dd>
                {offer.awaiting_role && (
                  <>
                    <dt className="text-muted-foreground">Waiting on</dt>
                    <dd>
                      {roleLabel(offer.awaiting_role)} (step {offer.approval_step})
                    </dd>
                  </>
                )}
              </dl>
              <DecisionHistory decisions={offer.decisions} currentUserId={currentUserId} />
              {offer.can_decide ? (
                <DecisionForm
                  key={offer.id}
                  api={api}
                  offer={offer}
                  onDone={(changedElsewhere) => refreshAfterDecision(offer.id, changedElsewhere)}
                />
              ) : (
                offer.status === "pending_approval" && (
                  <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                    Only a {roleLabel(offer.awaiting_role)?.toLowerCase()} can decide this step.
                  </p>
                )
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function DecisionHistory({ decisions, currentUserId }: { decisions: OfferDecision[]; currentUserId: string }) {
  return (
    <section aria-labelledby="offer-history-heading" className="space-y-2">
      <h3 id="offer-history-heading" className="text-sm font-medium">
        Decision history
      </h3>
      {decisions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No decisions yet.</p>
      ) : (
        <ol className="space-y-2">
          {decisions.map((decision) => (
            <li key={decision.step} className="rounded-lg border p-3 text-sm" data-step={decision.step}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">
                  Step {decision.step}: {decision.decision === "approved" ? "Approved" : "Rejected"}
                </span>
                <time className="text-xs text-muted-foreground" dateTime={decision.decided_at ?? undefined}>
                  {formatDecidedAt(decision.decided_at)}
                </time>
              </div>
              <p className="text-xs text-muted-foreground">by {actorLabel(decision.actor_id, currentUserId)}</p>
              {decision.reason !== null && <p className="mt-2 break-words whitespace-pre-wrap">{decision.reason}</p>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function DecisionForm({
  api,
  offer,
  onDone,
}: {
  api: OffersApi;
  offer: OfferDetail;
  onDone: (changedElsewhere: boolean) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState<OfferDecisionValue | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);

  async function decide(decision: OfferDecisionValue) {
    const invalid = reasonError(decision, reason);
    setError(invalid);
    setProblem(null);
    if (invalid) {
      reasonRef.current?.focus();
      return;
    }
    setSubmitting(decision);
    const result = await settle(
      api.POST("/v1/offers/{offer_id}/approvals", {
        params: { path: { offer_id: offer.id }, header: { "If-Match": ifMatch(offer.version) } },
        body: { decision, reason: reasonPayload(reason) },
      }),
    );
    setSubmitting(null);
    if (result.ok) {
      toast.success(decision === "approved" ? `Approved "${offer.title}".` : `Rejected "${offer.title}".`);
      await onDone(false);
    } else if (isStaleVersion(result.problem.status)) {
      await onDone(true);
    } else if (result.problem.status === 403) {
      toastProblem(result.problem);
      await onDone(false);
    } else {
      const fieldMessage = result.problem.errors?.find((item) => item.pointer.split("/").at(-1) === "reason")?.detail;
      if (fieldMessage) setError(fieldMessage);
      else setProblem(result.problem);
    }
  }

  const length = reason.trim().length;

  return (
    <section aria-labelledby="offer-decide-heading" className="space-y-3">
      <h3 id="offer-decide-heading" className="text-sm font-medium">
        Your decision
      </h3>
      <div className="grid gap-1.5">
        <label htmlFor="offer-reason" className="text-sm font-medium">
          Reason <span className="font-normal text-muted-foreground">(required to reject)</span>
        </label>
        <textarea
          id="offer-reason"
          ref={reasonRef}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={3}
          maxLength={REASON_MAX + 200}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "offer-reason-error offer-reason-count" : "offer-reason-count"}
          className="w-full min-w-0 rounded-lg border border-input bg-background px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive"
        />
        <div className="flex justify-between gap-2 text-xs">
          <p id="offer-reason-error" className="text-destructive" role={error ? "alert" : undefined}>
            {error}
          </p>
          <p id="offer-reason-count" className={length > REASON_MAX ? "text-destructive" : "text-muted-foreground"}>
            {length}/{REASON_MAX}
          </p>
        </div>
      </div>
      {problem && <FormProblem problem={problem} />}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void decide("approved")} disabled={submitting !== null}>
          <Check aria-hidden />
          {submitting === "approved" ? "Approving…" : "Approve"}
        </Button>
        <Button variant="destructive" onClick={() => void decide("rejected")} disabled={submitting !== null}>
          <X aria-hidden />
          {submitting === "rejected" ? "Rejecting…" : "Reject"}
        </Button>
      </div>
    </section>
  );
}
