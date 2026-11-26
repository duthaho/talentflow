"use client";

import { ArrowLeft, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi, settle, type ApiClient } from "@/lib/api/client";
import { describeProblem } from "@/lib/api/problem";
import { formatTimestamp, stageLabel, type CandidateCaseDetail } from "@/lib/candidates/detail";
import { useResource } from "@/lib/candidates/use-resource";

import { AttachmentsPanel } from "./attachments-panel";
import { AuditTimeline } from "./audit-timeline";
import { NoAccess, Panel } from "./panel";
import { RetentionPanel } from "./retention-panel";

export type DetailPermissions = { attachments: boolean; audit: boolean; retention: boolean };

export function CandidateDetail({
  candidateCaseId,
  currentUserId,
  permissions,
  api: injectedApi,
}: {
  candidateCaseId: string;
  currentUserId: string;
  permissions: DetailPermissions;
  api?: ApiClient;
}) {
  const api = useMemo(() => injectedApi ?? browserApi(), [injectedApi]);
  const [timelineRevision, setTimelineRevision] = useState(0);
  const candidate = useResource(
    useCallback(
      () => settle(api.GET("/v1/candidate-cases/{candidate_case_id}", { params: { path: { candidate_case_id: candidateCaseId } } })),
      [api, candidateCaseId],
    ),
  );
  const state = candidate.state;

  return (
    <div className="space-y-6">
      <Button asChild variant="ghost" size="sm">
        <Link href="/candidates">
          <ArrowLeft aria-hidden />
          Back to pipeline
        </Link>
      </Button>

      {state.status === "loading" && (
        <div aria-busy="true" className="space-y-3">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-24" />
        </div>
      )}

      {state.status === "error" && (
        <div role="alert" className="max-w-xl space-y-2 rounded-xl border p-4">
          <h1 className="text-xl font-semibold">
            {state.problem.status === 404 ? "Candidate not found" : describeProblem(state.problem).title}
          </h1>
          <p className="text-sm text-muted-foreground">
            {state.problem.status === 404
              ? "This candidate case doesn't exist, or it belongs to another tenant."
              : describeProblem(state.problem).description}
          </p>
          {describeProblem(state.problem).retryable && (
            <Button size="sm" variant="outline" onClick={candidate.reload}>
              <RefreshCw aria-hidden />
              Retry
            </Button>
          )}
        </div>
      )}

      {state.status === "ready" && (
        <>
          <Profile candidate={state.data} />
          <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
            <div className="space-y-6">
              {permissions.attachments ? (
                <AttachmentsPanel api={api} candidateCaseId={candidateCaseId} onUploaded={() => setTimelineRevision((value) => value + 1)} />
              ) : (
                <Panel id="attachments" title="Attachments">
                  <NoAccess>Your role can&apos;t view or upload attachments. Ask a tenant admin if you need access.</NoAccess>
                </Panel>
              )}
              {permissions.retention && <RetentionPanel api={api} candidateCaseId={candidateCaseId} currentUserId={currentUserId} />}
            </div>
            {permissions.audit ? (
              <AuditTimeline key={timelineRevision} api={api} candidateCaseId={candidateCaseId} currentUserId={currentUserId} />
            ) : (
              <Panel id="timeline" title="Audit timeline">
                <NoAccess>Your role can&apos;t view the audit timeline.</NoAccess>
              </Panel>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Profile({ candidate }: { candidate: CandidateCaseDetail }) {
  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          {candidate.first_name} {candidate.last_name}
        </h1>
        <Badge variant="secondary" aria-label={`Stage: ${stageLabel(candidate.stage)}`}>
          {stageLabel(candidate.stage)}
        </Badge>
      </div>
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-muted-foreground">Email</dt>
        <dd className="break-all">{candidate.email}</dd>
        <dt className="text-muted-foreground">Requisition</dt>
        <dd>
          <Link href={`/candidates?requisition=${encodeURIComponent(candidate.requisition_id)}`} className="underline underline-offset-4">
            View requisition pipeline
          </Link>
        </dd>
        <dt className="text-muted-foreground">Created</dt>
        <dd>
          <time dateTime={candidate.created_at}>{formatTimestamp(candidate.created_at)}</time>
        </dd>
      </dl>
    </header>
  );
}
