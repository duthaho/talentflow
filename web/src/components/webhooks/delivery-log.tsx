"use client";

import { RefreshCw, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { toastProblem } from "@/components/problem/toast-problem";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CONTROL_CLASS } from "@/components/pipeline/form-fields";
import { settle, type ApiClient } from "@/lib/api/client";
import { describeProblem } from "@/lib/api/problem";
import { formatTimestamp } from "@/lib/candidates/detail";
import { usePagedList } from "@/lib/offers/use-paged-list";
import { followDelivery } from "@/lib/webhooks/redelivery";
import {
  canRedeliver,
  DELIVERY_STATUS_LABELS,
  hostOf,
  isTerminal,
  lastResponseLabel,
  redeliveryOutcome,
  type DeliveryStatus,
  type WebhookDelivery,
  type WebhookEndpoint,
} from "@/lib/webhooks/format";

export const DELIVERY_PAGE_SIZE = 25;

const STATUS_VARIANTS: Record<DeliveryStatus, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "secondary",
  succeeded: "default",
  dead_lettered: "destructive",
  cancelled: "outline",
};

type RedeliveryResult = { tone: "info" | "success" | "error"; message: string };

function toneOf(delivery: WebhookDelivery): RedeliveryResult["tone"] {
  if (delivery.status === "succeeded") return "success";
  if (delivery.status === "pending") return "info";
  return "error";
}

export function DeliveryLog({
  api,
  endpoint,
  pollIntervalMs = 2000,
  pollTimeoutMs = 60000,
}: {
  api: ApiClient;
  endpoint: WebhookEndpoint;
  pollIntervalMs?: number;
  pollTimeoutMs?: number;
}) {
  const [statusFilter, setStatusFilter] = useState<DeliveryStatus | "">("");
  const [redelivering, setRedelivering] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, RedeliveryResult>>({});
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const log = usePagedList(
    useCallback(
      (cursor: string | null) =>
        settle(
          api.GET("/v1/webhook-endpoints/{endpoint_id}/deliveries", {
            params: {
              path: { endpoint_id: endpoint.id },
              query: { status: statusFilter ? [statusFilter] : undefined, cursor: cursor ?? undefined, limit: DELIVERY_PAGE_SIZE },
            },
          }),
        ),
      [api, endpoint.id, statusFilter],
    ),
  );

  async function redeliver(original: WebhookDelivery) {
    setRedelivering(original.id);
    const queued = await settle(
      api.POST("/v1/webhook-deliveries/{delivery_id}/redeliveries", {
        params: { path: { delivery_id: original.id }, header: { "Idempotency-Key": crypto.randomUUID() } },
      }),
    );
    if (!mounted.current) return;
    setRedelivering(null);
    if (!queued.ok) {
      setResults((current) => ({ ...current, [original.id]: { tone: "error", message: describeProblem(queued.problem).description } }));
      return;
    }
    const show = (delivery: WebhookDelivery, suffix = "") =>
      setResults((current) => ({ ...current, [original.id]: { tone: toneOf(delivery), message: `${redeliveryOutcome(delivery)}${suffix}` } }));
    show(queued.data);
    const final = await followDelivery(api, queued.data, {
      intervalMs: pollIntervalMs,
      timeoutMs: pollTimeoutMs,
      onUpdate: show,
      isActive: () => mounted.current,
    });
    if (mounted.current && !isTerminal(final.status)) show(final, " Refresh the log later to see the outcome.");
  }

  const headingId = `deliveries-${endpoint.id}-heading`;
  const { list } = log;
  return (
    <section aria-labelledby={headingId} aria-busy={list.status === "loading" || list.loadingMore} className="space-y-3">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-lg font-medium">
            Delivery log: {hostOf(endpoint.url)}
          </h2>
          <p className="text-sm text-muted-foreground">Newest first. Redelivery sends the same event again with the same webhook-id.</p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="delivery-status" className="text-sm text-muted-foreground">
            Status
          </label>
          <select
            id="delivery-status"
            className={`${CONTROL_CLASS} w-40`}
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as DeliveryStatus | "")}
          >
            <option value="">All statuses</option>
            {Object.entries(DELIVERY_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <Button variant="outline" size="sm" onClick={log.reload}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        </div>
      </header>

      {endpoint.status !== "enabled" && (
        <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">Enable this endpoint to redeliver events to it.</p>
      )}

      {list.status === "loading" && (
        <div className="space-y-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      )}
      {list.status === "error" && list.problem && (
        <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 p-3 text-sm">
          <p className="font-medium text-destructive">{describeProblem(list.problem).title}</p>
          <p className="text-muted-foreground">{describeProblem(list.problem).description}</p>
          <Button size="sm" variant="outline" onClick={log.reload}>
            Retry
          </Button>
        </div>
      )}
      {list.status === "ready" && list.items.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          {statusFilter ? `No ${DELIVERY_STATUS_LABELS[statusFilter].toLowerCase()} deliveries.` : "No deliveries yet. They appear when a subscribed event happens."}
        </p>
      )}
      {list.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <caption className="sr-only">Deliveries to {hostOf(endpoint.url)}</caption>
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="p-2 font-medium">Event</th>
                <th scope="col" className="p-2 font-medium">Status</th>
                <th scope="col" className="p-2 font-medium">Attempts</th>
                <th scope="col" className="p-2 font-medium">Last response</th>
                <th scope="col" className="p-2 font-medium">Created</th>
                <th scope="col" className="p-2 font-medium">Last attempt</th>
                <th scope="col" className="p-2 font-medium">Completed</th>
                <th scope="col" className="p-2 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((delivery) => {
                const result = results[delivery.id];
                return (
                  <DeliveryRow
                    key={delivery.id}
                    delivery={delivery}
                    redeliverable={canRedeliver(delivery, endpoint)}
                    busy={redelivering !== null}
                    redelivering={redelivering === delivery.id}
                    result={result}
                    onRedeliver={() => void redeliver(delivery)}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {list.status === "ready" && list.nextCursor && (
        <Button size="sm" variant="ghost" onClick={() => void log.loadMore(toastProblem)} disabled={list.loadingMore}>
          {list.loadingMore ? "Loading…" : "Load more"}
        </Button>
      )}
    </section>
  );
}

function DeliveryRow({
  delivery,
  redeliverable,
  busy,
  redelivering,
  result,
  onRedeliver,
}: {
  delivery: WebhookDelivery;
  redeliverable: boolean;
  busy: boolean;
  redelivering: boolean;
  result?: RedeliveryResult;
  onRedeliver: () => void;
}) {
  const label = `${delivery.event_type} ${delivery.event_id.slice(0, 8)}`;
  return (
    <>
      <tr data-delivery-id={delivery.id} className="border-t align-top">
        <td className="p-2">
          <span className="block font-mono text-xs">{delivery.event_type}</span>
          <span className="block font-mono text-xs text-muted-foreground" title={delivery.event_id}>
            {delivery.event_id.slice(0, 8)}
            {delivery.kind === "redelivery" && " · redelivery"}
          </span>
        </td>
        <td className="p-2">
          <Badge variant={STATUS_VARIANTS[delivery.status]}>{DELIVERY_STATUS_LABELS[delivery.status]}</Badge>
        </td>
        <td className="p-2 tabular-nums">
          {delivery.attempt_count} / {delivery.max_attempts}
        </td>
        <td className="p-2">{lastResponseLabel(delivery)}</td>
        <td className="p-2 whitespace-nowrap">{formatTimestamp(delivery.created_at)}</td>
        <td className="p-2 whitespace-nowrap">{formatTimestamp(delivery.last_attempt_at)}</td>
        <td className="p-2 whitespace-nowrap">{formatTimestamp(delivery.completed_at)}</td>
        <td className="p-2 text-right">
          {redeliverable && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onRedeliver} aria-label={`Redeliver ${label}`}>
              <RotateCcw aria-hidden />
              {redelivering ? "Redelivering…" : "Redeliver"}
            </Button>
          )}
        </td>
      </tr>
      {result && (
        <tr className="border-t-0">
          <td colSpan={8} className="px-2 pb-2">
            <p
              role={result.tone === "error" ? "alert" : "status"}
              className={
                result.tone === "error"
                  ? "rounded-md bg-destructive/10 p-2 text-destructive"
                  : result.tone === "success"
                    ? "rounded-md bg-primary/10 p-2"
                    : "rounded-md bg-muted p-2"
              }
            >
              <span className="sr-only">Redelivery result for {label}: </span>
              {result.message}
            </p>
          </td>
        </tr>
      )}
    </>
  );
}
