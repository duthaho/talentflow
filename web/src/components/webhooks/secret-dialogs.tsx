"use client";

import { Copy, TriangleAlert } from "lucide-react";
import { useState, type FormEvent } from "react";

import { FormProblem } from "@/components/pipeline/form-fields";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { settle, type ApiClient } from "@/lib/api/client";
import { ifMatch } from "@/lib/api/precondition";
import type { ProblemDetails } from "@/lib/api/problem";
import { formatTimestamp } from "@/lib/candidates/detail";
import { GRACE_PERIODS, hostOf, isStale, type PlaintextSecret, type WebhookEndpoint } from "@/lib/webhooks/format";

export type RevealedSecret = { secret: PlaintextSecret; host: string; reason: "created" | "rotated"; previousExpiresAt?: string };

export function SecretRevealDialog({ revealed, onDone }: { revealed: RevealedSecret | null; onDone: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!revealed) return;
    try {
      await navigator.clipboard.writeText(revealed.secret.value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  function close(open: boolean) {
    if (open) return;
    setCopied(false);
    onDone();
  }

  return (
    <Dialog open={revealed !== null} onOpenChange={close}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{revealed?.reason === "rotated" ? "New signing secret" : "Endpoint created"}</DialogTitle>
          <DialogDescription>Signing secret for {revealed?.host}. Install it in the receiver to verify the <code>webhook-signature</code> header.</DialogDescription>
        </DialogHeader>
        <Alert>
          <TriangleAlert aria-hidden />
          <AlertTitle>This is the only time the secret is shown</AlertTitle>
          <AlertDescription>
            Store it in the receiver&apos;s secret manager now. TalentFlow cannot show it again; rotate the secret if you lose it.
            {revealed?.previousExpiresAt && <span className="block">The previous secret keeps signing until {formatTimestamp(revealed.previousExpiresAt)}.</span>}
          </AlertDescription>
        </Alert>
        <div className="grid gap-1.5">
          <label htmlFor="webhook-secret" className="text-sm font-medium">
            Signing secret
          </label>
          <div className="flex gap-2">
            <input
              id="webhook-secret"
              readOnly
              value={revealed?.secret.value ?? ""}
              onFocus={(event) => event.currentTarget.select()}
              autoComplete="off"
              spellCheck={false}
              className="h-8 w-full min-w-0 rounded-lg border border-input bg-muted px-2.5 font-mono text-sm"
            />
            <Button type="button" variant="outline" onClick={() => void copy()}>
              <Copy aria-hidden />
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <p role="status" className="sr-only">
            {copied ? "Secret copied to the clipboard." : ""}
          </p>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button">I&apos;ve stored the secret</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RotateSecretDialog({
  api,
  endpoint,
  onOpenChange,
  onRotated,
  onStale,
}: {
  api: ApiClient;
  endpoint: WebhookEndpoint | null;
  onOpenChange: (open: boolean) => void;
  onRotated: (endpoint: WebhookEndpoint, revealed: RevealedSecret) => void;
  onStale: (problem: ProblemDetails) => void;
}) {
  const [grace, setGrace] = useState<number>(GRACE_PERIODS[0].seconds);
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function changeOpen(open: boolean) {
    if (!open) {
      setProblem(null);
      setGrace(GRACE_PERIODS[0].seconds);
    }
    onOpenChange(open);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!endpoint) return;
    setSubmitting(true);
    setProblem(null);
    const result = await settle(
      api.POST("/v1/webhook-endpoints/{endpoint_id}/secret-rotations", {
        params: { path: { endpoint_id: endpoint.id }, header: { "If-Match": ifMatch(endpoint.version) } },
        body: { grace_period_seconds: grace },
      }),
    );
    setSubmitting(false);
    if (!result.ok) {
      if (isStale(result.problem)) onStale(result.problem);
      else setProblem(result.problem);
      return;
    }
    setGrace(GRACE_PERIODS[0].seconds);
    onRotated(result.data.endpoint, {
      secret: result.data.secret,
      host: hostOf(result.data.endpoint.url),
      reason: "rotated",
      previousExpiresAt: result.data.previous_secret_expires_at,
    });
  }

  return (
    <Dialog open={endpoint !== null} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rotate signing secret</DialogTitle>
          <DialogDescription>
            {endpoint ? `For ${hostOf(endpoint.url)}. ` : ""}A new secret signs every request from now on. During the grace period the old secret signs too, so the receiver can switch over.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)} className="grid gap-4">
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">Old secret keeps signing for</legend>
            {GRACE_PERIODS.map((option) => (
              <label key={option.seconds} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="grace_period_seconds"
                  className="size-4 accent-primary"
                  checked={grace === option.seconds}
                  onChange={() => setGrace(option.seconds)}
                />
                {option.label}
              </label>
            ))}
          </fieldset>
          {problem && <FormProblem problem={problem} />}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Rotating…" : "Rotate secret"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
