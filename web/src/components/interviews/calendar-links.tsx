"use client";

import { CalendarPlus, Copy, Link2Off } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { FormProblem } from "@/components/pipeline/form-fields";
import { toastProblem } from "@/components/problem/toast-problem";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { settle } from "@/lib/api/client";
import { describeProblem, type ProblemDetails } from "@/lib/api/problem";
import type { CalendarSubscription, CalendarSubscriptionSummary, InterviewsApi } from "@/lib/interviews/contract";
import { formatDate } from "@/lib/interviews/format";

type Links = { status: "loading" } | { status: "error"; problem: ProblemDetails } | { status: "ready"; items: CalendarSubscriptionSummary[] };

function shortId(id: string): string {
  return id.slice(0, 6);
}

export function CalendarLinks({ api }: { api: InterviewsApi }) {
  const [links, setLinks] = useState<Links>({ status: "loading" });
  const [reloads, setReloads] = useState(0);
  const [creating, setCreating] = useState(false);
  const [revealed, setRevealed] = useState<CalendarSubscription | null>(null);
  const [revoking, setRevoking] = useState<CalendarSubscriptionSummary | null>(null);

  useEffect(() => {
    let current = true;
    void settle(api.GET("/v1/calendar-subscriptions", { params: { query: { interviewer: "me" } } })).then((result) => {
      if (!current) return;
      setLinks(result.ok ? { status: "ready", items: result.data } : { status: "error", problem: result.problem });
    });
    return () => {
      current = false;
    };
  }, [api, reloads]);

  const reload = useCallback(() => {
    setLinks({ status: "loading" });
    setReloads((count) => count + 1);
  }, []);

  async function create() {
    setCreating(true);
    const result = await settle(api.POST("/v1/calendar-subscriptions", { body: {} }));
    setCreating(false);
    if (!result.ok) {
      toastProblem(result.problem);
      return;
    }
    setRevealed(result.data);
    reload();
  }

  function removeLink(id: string) {
    setLinks((current) => (current.status === "ready" ? { ...current, items: current.items.filter((item) => item.id !== id) } : current));
  }

  const headingId = "calendar-links-heading";
  return (
    <section aria-labelledby={headingId} aria-busy={links.status === "loading"} data-section="calendar-links" className="space-y-3">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-lg font-medium">
            Calendar subscription
          </h2>
          <p className="text-sm text-muted-foreground">
            Subscribe Google Calendar, Outlook or Apple Calendar to your interviews. Anyone with the link can read your schedule, so
            revoke it if it leaks.
          </p>
        </div>
        <Button variant="outline" onClick={() => void create()} disabled={creating}>
          <CalendarPlus aria-hidden />
          {creating ? "Generating…" : "Generate link"}
        </Button>
      </header>

      {links.status === "loading" && <Skeleton className="h-12" />}
      {links.status === "error" && (
        <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 p-3 text-sm">
          <p className="font-medium text-destructive">{describeProblem(links.problem).title}</p>
          <p className="text-muted-foreground">{describeProblem(links.problem).description}</p>
          <Button size="sm" variant="outline" onClick={reload}>
            Retry
          </Button>
        </div>
      )}
      {links.status === "ready" && links.items.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">You have no active calendar links.</p>
      )}
      {links.status === "ready" && links.items.length > 0 && (
        <ul className="space-y-2">
          {links.items.map((link) => (
            <li key={link.id} data-link-id={link.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-3">
              <div className="min-w-0 text-sm">
                <p className="font-medium">Link {shortId(link.id)}</p>
                <p className="text-muted-foreground">
                  Created {formatDate(link.created_at)} · expires {formatDate(link.expires_at)}
                </p>
              </div>
              <Button size="sm" variant="outline" aria-label={`Revoke link ${shortId(link.id)}`} onClick={() => setRevoking(link)}>
                <Link2Off aria-hidden />
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}

      <RevealDialog subscription={revealed} onClose={() => setRevealed(null)} />
      <RevokeDialog
        api={api}
        link={revoking}
        onClose={() => setRevoking(null)}
        onRevoked={(link, alreadyGone) => {
          removeLink(link.id);
          setRevoking(null);
          toast.success(alreadyGone ? `Link ${shortId(link.id)} was already revoked or expired.` : `Link ${shortId(link.id)} revoked. Calendars using it stop updating.`);
        }}
      />
    </section>
  );
}

function RevealDialog({ subscription, onClose }: { subscription: CalendarSubscription | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!subscription) return;
    try {
      await navigator.clipboard.writeText(subscription.feed_url);
      setCopied(true);
    } catch {
      toast.error("Copy failed", { description: "Select the link and copy it manually." });
    }
  }

  return (
    <Dialog
      open={subscription !== null}
      onOpenChange={(open) => {
        if (!open) {
          setCopied(false);
          onClose();
        }
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Your calendar link</DialogTitle>
          <DialogDescription>Add it to your calendar app as a subscription (“From URL”).</DialogDescription>
        </DialogHeader>
        <Alert>
          <AlertTitle>Shown only once</AlertTitle>
          <AlertDescription>
            TalentFlow does not store this link and cannot show it again. Copy it now. If you lose it, generate a new one and revoke this
            one.
          </AlertDescription>
        </Alert>
        <div className="grid gap-1.5">
          <label htmlFor="calendar-feed-url" className="text-sm font-medium">
            Feed URL
          </label>
          <input
            id="calendar-feed-url"
            readOnly
            value={subscription?.feed_url ?? ""}
            onFocus={(event) => event.currentTarget.select()}
            className="h-8 w-full min-w-0 rounded-lg border border-input bg-muted px-2.5 font-mono text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          {subscription && <p className="text-xs text-muted-foreground">Expires {formatDate(subscription.expires_at)}.</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => void copy()}>
            <Copy aria-hidden />
            {copied ? "Copied" : "Copy link"}
          </Button>
          <DialogClose asChild>
            <Button type="button">Done</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevokeDialog({
  api,
  link,
  onClose,
  onRevoked,
}: {
  api: InterviewsApi;
  link: CalendarSubscriptionSummary | null;
  onClose: () => void;
  onRevoked: (link: CalendarSubscriptionSummary, alreadyGone: boolean) => void;
}) {
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function revoke() {
    if (!link) return;
    setSubmitting(true);
    setProblem(null);
    const result = await settle(api.DELETE("/v1/calendar-subscriptions/{subscription_id}", { params: { path: { subscription_id: link.id } } }));
    setSubmitting(false);
    if (result.ok || result.problem.status === 404) onRevoked(link, !result.ok);
    else setProblem(result.problem);
  }

  return (
    <Dialog
      open={link !== null}
      onOpenChange={(open) => {
        if (!open) {
          setProblem(null);
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Revoke calendar link?</DialogTitle>
          <DialogDescription>
            {link ? `Link ${shortId(link.id)} stops working immediately. ` : ""}Calendars subscribed with it no longer receive your interviews.
          </DialogDescription>
        </DialogHeader>
        {problem && <FormProblem problem={problem} />}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button type="button" variant="destructive" disabled={submitting} onClick={() => void revoke()}>
            {submitting ? "Revoking…" : "Revoke link"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
