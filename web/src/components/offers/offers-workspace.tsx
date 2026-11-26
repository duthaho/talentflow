"use client";

import { ChevronRight, FilePlus2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { CONTROL_CLASS } from "@/components/pipeline/form-fields";
import { toastProblem } from "@/components/problem/toast-problem";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { settle } from "@/lib/api/client";
import { describeProblem } from "@/lib/api/problem";
import { browserOffersApi, type OfferStatus, type OfferSummary, type OffersApi } from "@/lib/offers/contract";
import { formatSalary, roleLabel, STATUS_LABELS } from "@/lib/offers/format";
import { usePagedList, type PagedList } from "@/lib/offers/use-paged-list";

import { CreateOfferDialog, type OfferCandidate } from "./create-offer-dialog";
import { OfferSheet } from "./offer-sheet";
import { OfferStatusBadge } from "./offer-status-badge";

export const PAGE_SIZE = 25;

type Names = ReadonlyMap<string, string | null>;

function fullName(person: { first_name: string; last_name: string }): string {
  return `${person.first_name} ${person.last_name}`;
}

function setOfferParam(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("offer", id);
  else url.searchParams.delete("offer");
  window.history.replaceState(null, "", url);
}

function useCandidateNames(api: OffersApi, offers: OfferSummary[]) {
  const [names, setNames] = useState<Names>(new Map());
  const requested = useRef(new Set<string>());

  const remember = useCallback((entries: [string, string][]) => {
    if (entries.length === 0) return;
    for (const [id] of entries) requested.current.add(id);
    setNames((current) => new Map([...current, ...entries]));
  }, []);

  useEffect(() => {
    const missing = [...new Set(offers.map((offer) => offer.candidate_case_id))].filter((id) => !requested.current.has(id));
    for (const id of missing) {
      requested.current.add(id);
      void settle(api.GET("/v1/candidate-cases/{candidate_case_id}", { params: { path: { candidate_case_id: id } } })).then((result) =>
        setNames((current) => new Map(current).set(id, result.ok ? fullName(result.data) : null)),
      );
    }
  }, [api, offers]);

  const nameOf = useCallback(
    (id: string) => {
      const name = names.get(id);
      return name ?? (names.has(id) ? `Candidate ${id.slice(0, 8)}` : "Loading candidate…");
    },
    [names],
  );

  return { nameOf, remember };
}

export function OffersWorkspace({
  currentUserId,
  canCreate,
  initialOfferId,
  api: injectedApi,
}: {
  currentUserId: string;
  canCreate: boolean;
  initialOfferId: string | null;
  api?: OffersApi;
}) {
  const api = useMemo(() => injectedApi ?? browserOffersApi(), [injectedApi]);
  const [statusFilter, setStatusFilter] = useState<OfferStatus | "">("");
  const [openOfferId, setOpenOfferId] = useState(initialOfferId);
  const [creating, setCreating] = useState<OfferCandidate | null>(null);

  const inbox = usePagedList(
    useCallback(
      (cursor: string | null) =>
        settle(api.GET("/v1/offers", { params: { query: { awaiting: "me", cursor: cursor ?? undefined, limit: PAGE_SIZE } } })),
      [api],
    ),
  );
  const all = usePagedList(
    useCallback(
      (cursor: string | null) =>
        settle(
          api.GET("/v1/offers", {
            params: { query: { status: statusFilter || undefined, cursor: cursor ?? undefined, limit: PAGE_SIZE } },
          }),
        ),
      [api, statusFilter],
    ),
  );
  const ready = usePagedList(
    useCallback(
      (cursor: string | null) =>
        canCreate
          ? settle(
              api.GET("/v1/candidate-cases", {
                params: { query: { stage: "interviewing", cursor: cursor ?? undefined, limit: PAGE_SIZE } },
              }),
            )
          : Promise.resolve({ ok: true as const, data: { items: [], next_cursor: null, total: 0 } }),
      [api, canCreate],
    ),
  );

  const offers = useMemo(() => [...inbox.list.items, ...all.list.items], [inbox.list.items, all.list.items]);
  const { nameOf, remember } = useCandidateNames(api, offers);
  const { reload: reloadInbox } = inbox;
  const { reload: reloadAll } = all;

  useEffect(() => {
    remember(ready.list.items.map((candidate) => [candidate.id, fullName(candidate)]));
  }, [ready.list.items, remember]);

  function openOffer(id: string | null) {
    setOpenOfferId(id);
    setOfferParam(id);
  }

  const refreshOffers = useCallback(() => {
    reloadInbox();
    reloadAll();
  }, [reloadInbox, reloadAll]);

  function refreshAll() {
    refreshOffers();
    ready.reload();
  }

  return (
    <div className="space-y-8">
      <div className="flex justify-end">
        <Button variant="outline" onClick={refreshAll}>
          <RefreshCw aria-hidden />
          Refresh
        </Button>
      </div>

      <Section
        id="offers-inbox"
        title="Awaiting your approval"
        list={inbox.list}
        empty="Nothing is waiting on you. Offers appear here when they reach the approval step for your role."
        onRetry={inbox.reload}
        onLoadMore={() => void inbox.loadMore(toastProblem)}
      >
        {inbox.list.items.map((offer) => (
          <OfferRow key={offer.id} offer={offer} candidate={nameOf(offer.candidate_case_id)} onOpen={() => openOffer(offer.id)} />
        ))}
      </Section>

      {canCreate && (
        <Section
          id="offers-ready"
          title="Ready for an offer"
          description="Candidates in the Interviewing stage without an offer."
          list={ready.list}
          empty="No candidates are in the Interviewing stage."
          onRetry={ready.reload}
          onLoadMore={() => void ready.loadMore(toastProblem)}
        >
          {ready.list.items.map((candidate) => (
            <li key={candidate.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-3">
              <div className="min-w-0">
                <p className="truncate font-medium">{fullName(candidate)}</p>
                <p className="truncate text-sm text-muted-foreground">{candidate.email}</p>
              </div>
              <Button
                size="sm"
                aria-label={`Create offer for ${fullName(candidate)}`}
                onClick={() => setCreating({ id: candidate.id, name: fullName(candidate) })}
              >
                <FilePlus2 aria-hidden />
                Create offer
              </Button>
            </li>
          ))}
        </Section>
      )}

      <Section
        id="offers-all"
        title="All offers"
        list={all.list}
        empty={statusFilter ? `No ${STATUS_LABELS[statusFilter].toLowerCase()} offers.` : "No offers yet."}
        onRetry={all.reload}
        onLoadMore={() => void all.loadMore(toastProblem)}
        actions={
          <div className="flex items-center gap-2">
            <label htmlFor="offers-status" className="text-sm text-muted-foreground">
              Status
            </label>
            <select
              id="offers-status"
              className={`${CONTROL_CLASS} w-44`}
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as OfferStatus | "")}
            >
              <option value="">All statuses</option>
              {Object.entries(STATUS_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {all.list.items.map((offer) => (
          <OfferRow key={offer.id} offer={offer} candidate={nameOf(offer.candidate_case_id)} onOpen={() => openOffer(offer.id)} />
        ))}
      </Section>

      <OfferSheet
        api={api}
        offerId={openOfferId}
        currentUserId={currentUserId}
        candidateName={nameOf}
        onClose={() => openOffer(null)}
        onDecided={refreshOffers}
      />

      <CreateOfferDialog
        api={api}
        candidate={creating}
        onOpenChange={(open) => !open && setCreating(null)}
        onCreated={(offerId) => {
          if (creating) {
            ready.remove(creating.id);
            toast.success(`Offer created for ${creating.name}. It now waits for hiring manager approval.`);
          }
          setCreating(null);
          refreshOffers();
          openOffer(offerId);
        }}
      />
    </div>
  );
}

function Section<T>({
  id,
  title,
  description,
  list,
  empty,
  actions,
  onRetry,
  onLoadMore,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  list: PagedList<T>;
  empty: string;
  actions?: ReactNode;
  onRetry: () => void;
  onLoadMore: () => void;
  children: ReactNode;
}) {
  const headingId = `${id}-heading`;
  return (
    <section aria-labelledby={headingId} aria-busy={list.status === "loading" || list.loadingMore} data-section={id} className="space-y-3">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={headingId} className="flex items-center gap-2 text-lg font-medium">
            {title}
            {list.status === "ready" && (
              <Badge variant="secondary" aria-label={`${list.total} total`}>
                {list.total}
              </Badge>
            )}
          </h2>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </header>
      {list.status === "loading" && (
        <div className="space-y-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      )}
      {list.status === "error" && list.problem && (
        <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 p-3 text-sm">
          <p className="font-medium text-destructive">{describeProblem(list.problem).title}</p>
          <p className="text-muted-foreground">{describeProblem(list.problem).description}</p>
          <Button size="sm" variant="outline" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
      {list.status === "ready" && list.items.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">{empty}</p>
      )}
      {list.items.length > 0 && <ul className="space-y-2">{children}</ul>}
      {list.status === "ready" && list.nextCursor && (
        <Button size="sm" variant="ghost" onClick={onLoadMore} disabled={list.loadingMore}>
          {list.loadingMore ? "Loading…" : `Load more (${Math.max(0, list.total - list.items.length)} left)`}
        </Button>
      )}
    </section>
  );
}

function OfferRow({ offer, candidate, onOpen }: { offer: OfferSummary; candidate: string; onOpen: () => void }) {
  return (
    <li data-offer-id={offer.id}>
      <button
        type="button"
        onClick={onOpen}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 rounded-lg border bg-card p-3 text-left transition-colors outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 sm:grid-cols-[2fr_1fr_auto_auto]"
      >
        <span className="min-w-0">
          <span className="block truncate font-medium">{offer.title}</span>
          <span className="block truncate text-sm text-muted-foreground">{candidate}</span>
        </span>
        <span className="hidden text-sm tabular-nums sm:block">{formatSalary(offer.annual_salary, offer.currency)}</span>
        <span className="flex flex-col items-end gap-1 sm:items-start">
          <OfferStatusBadge status={offer.status} />
          {offer.awaiting_role && <span className="text-xs text-muted-foreground">Waiting on {roleLabel(offer.awaiting_role)}</span>}
        </span>
        <ChevronRight aria-hidden className="hidden size-4 text-muted-foreground sm:block" />
        <span className="sr-only">{offer.can_decide ? "Your decision is needed. " : ""}Open offer</span>
      </button>
    </li>
  );
}
