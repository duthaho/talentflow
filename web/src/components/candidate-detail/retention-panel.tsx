"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useCallback } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { settle, type ApiClient } from "@/lib/api/client";
import { actorLabel, formatTimestamp } from "@/lib/candidates/detail";
import { useResource } from "@/lib/candidates/use-resource";

import { Panel, PanelProblem } from "./panel";

export function RetentionPanel({ api, candidateCaseId, currentUserId }: { api: ApiClient; candidateCaseId: string; currentUserId: string }) {
  const hold = useResource(
    useCallback(
      () => settle(api.GET("/v1/candidate-cases/{candidate_case_id}/legal-hold", { params: { path: { candidate_case_id: candidateCaseId } } })),
      [api, candidateCaseId],
    ),
  );
  const policy = useResource(useCallback(() => settle(api.GET("/v1/retention-policy")), [api]));

  return (
    <Panel id="retention" title="Retention and legal hold" busy={hold.state.status === "loading" || policy.state.status === "loading"}>
      <div className="space-y-1.5">
        <h3 className="text-sm font-medium">Legal hold</h3>
        {hold.state.status === "loading" && <Skeleton className="h-10" />}
        {hold.state.status === "error" && <PanelProblem problem={hold.state.problem} what="the legal hold" onRetry={hold.reload} />}
        {hold.state.status === "ready" &&
          (hold.state.data.held ? (
            <div className="space-y-1 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
              <p className="flex items-center gap-2 font-medium">
                <ShieldAlert aria-hidden className="size-4" />
                On hold — excluded from retention purge
              </p>
              {hold.state.data.reason && <p className="break-words whitespace-pre-wrap">{hold.state.data.reason}</p>}
              <p className="text-xs text-muted-foreground">
                Placed by {actorLabel(hold.state.data.placed_by, currentUserId)} on {formatTimestamp(hold.state.data.placed_at)}
              </p>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <ShieldCheck aria-hidden className="size-4" />
              No legal hold
            </p>
          ))}
      </div>
      <div className="space-y-1.5">
        <h3 className="text-sm font-medium">Tenant retention policy</h3>
        {policy.state.status === "loading" && <Skeleton className="h-6" />}
        {policy.state.status === "error" && <PanelProblem problem={policy.state.problem} what="the retention policy" onRetry={policy.reload} />}
        {policy.state.status === "ready" && (
          <p className="text-sm text-muted-foreground">
            {policy.state.data.retention_days === null
              ? "No retention policy is set, so closed cases are kept until one is."
              : `Rejected and withdrawn cases are anonymized ${policy.state.data.retention_days} days after they close, unless on legal hold.`}
          </p>
        )}
      </div>
    </Panel>
  );
}
