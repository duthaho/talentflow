"use client";

import { useCallback } from "react";

import { toastProblem } from "@/components/problem/toast-problem";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { settle, type ApiClient } from "@/lib/api/client";
import { actorLabel, describeEvent, formatTimestamp } from "@/lib/candidates/detail";
import { usePagedList } from "@/lib/offers/use-paged-list";

import { Panel, PanelProblem } from "./panel";

export const TIMELINE_PAGE_SIZE = 20;

export function AuditTimeline({ api, candidateCaseId, currentUserId }: { api: ApiClient; candidateCaseId: string; currentUserId: string }) {
  const { list, reload, loadMore } = usePagedList(
    useCallback(
      (cursor: string | null) =>
        settle(
          api.GET("/v1/candidate-cases/{candidate_case_id}/audit-events", {
            params: { path: { candidate_case_id: candidateCaseId }, query: { cursor: cursor ?? undefined, limit: TIMELINE_PAGE_SIZE } },
          }),
        ),
      [api, candidateCaseId],
    ),
  );

  return (
    <Panel id="timeline" title="Audit timeline" description="Changes to this case and its attachments, newest first." busy={list.status === "loading" || list.loadingMore}>
      {list.status === "loading" && (
        <div className="space-y-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      )}
      {list.status === "error" && list.problem && <PanelProblem problem={list.problem} what="the audit timeline" onRetry={reload} />}
      {list.status === "ready" && list.items.length === 0 && (
        <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">No recorded activity yet.</p>
      )}
      {list.items.length > 0 && (
        <ol className="relative space-y-4 border-l pl-4">
          {list.items.map((event) => {
            const view = describeEvent(event);
            return (
              <li key={event.id} data-event-id={event.id} className="text-sm">
                <span aria-hidden className="absolute -left-1 mt-1.5 size-2 rounded-full bg-muted-foreground" />
                <p className="font-medium">{view.title}</p>
                {view.detail && <p>{view.detail}</p>}
                <p className="text-xs text-muted-foreground">
                  {actorLabel(event.actor_id, currentUserId)} · <time dateTime={event.occurred_at}>{formatTimestamp(event.occurred_at)}</time>
                </p>
              </li>
            );
          })}
        </ol>
      )}
      {list.status === "ready" && list.nextCursor && (
        <Button size="sm" variant="ghost" onClick={() => void loadMore(toastProblem)} disabled={list.loadingMore}>
          {list.loadingMore ? "Loading…" : "Show older activity"}
        </Button>
      )}
    </Panel>
  );
}
