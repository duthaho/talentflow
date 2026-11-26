"use client";

import { CalendarClock, MessageSquarePlus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Section } from "@/components/offers/offers-workspace";
import { CONTROL_CLASS } from "@/components/pipeline/form-fields";
import { toastProblem } from "@/components/problem/toast-problem";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { settle } from "@/lib/api/client";
import { browserInterviewsApi, type Interviewer, type InterviewListItem, type InterviewsApi } from "@/lib/interviews/contract";
import { formatDateTime } from "@/lib/interviews/format";
import { usePagedList } from "@/lib/offers/use-paged-list";

import { CalendarLinks } from "./calendar-links";
import { FeedbackDialog } from "./feedback-dialog";
import { interviewerLabel, ScheduleInterviewDialog } from "./schedule-interview-dialog";

export const PAGE_SIZE = 25;

export type InterviewPermissions = { manage: boolean; submitFeedback: boolean; calendarSelf: boolean };

function useInterviewers(api: InterviewsApi, enabled: boolean) {
  const [interviewers, setInterviewers] = useState<Interviewer[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let current = true;
    void settle(api.GET("/v1/interviewers")).then((result) => current && result.ok && setInterviewers(result.data.items));
    return () => {
      current = false;
    };
  }, [api, enabled]);
  return interviewers;
}

export function InterviewsWorkspace({ permissions, api: injectedApi }: { permissions: InterviewPermissions; api?: InterviewsApi }) {
  const api = useMemo(() => injectedApi ?? browserInterviewsApi(), [injectedApi]);
  const [interviewerFilter, setInterviewerFilter] = useState("");
  const [scheduling, setScheduling] = useState(false);
  const [reviewing, setReviewing] = useState<InterviewListItem | null>(null);
  const [submitted, setSubmitted] = useState<ReadonlySet<string>>(new Set());
  const interviewers = useInterviewers(api, permissions.manage);

  const mine = usePagedList(
    useCallback(
      (cursor: string | null) =>
        permissions.submitFeedback
          ? settle(api.GET("/v1/interviews", { params: { query: { interviewer: "me", cursor: cursor ?? undefined, limit: PAGE_SIZE } } }))
          : Promise.resolve({ ok: true as const, data: { items: [], next_cursor: null, total: 0 } }),
      [api, permissions.submitFeedback],
    ),
  );
  const all = usePagedList(
    useCallback(
      (cursor: string | null) =>
        permissions.manage
          ? settle(
              api.GET("/v1/interviews", {
                params: { query: { interviewer: interviewerFilter || undefined, cursor: cursor ?? undefined, limit: PAGE_SIZE } },
              }),
            )
          : Promise.resolve({ ok: true as const, data: { items: [], next_cursor: null, total: 0 } }),
      [api, permissions.manage, interviewerFilter],
    ),
  );

  function hasFeedback(interview: InterviewListItem): boolean {
    return interview.feedback_submitted || submitted.has(interview.id);
  }

  function markSubmitted(interview: InterviewListItem) {
    setSubmitted((current) => new Set(current).add(interview.id));
  }

  function refresh() {
    setSubmitted(new Set());
    mine.reload();
    all.reload();
  }

  const pending = mine.list.items.filter((interview) => !hasFeedback(interview)).length;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" onClick={refresh}>
          <RefreshCw aria-hidden />
          Refresh
        </Button>
        {permissions.manage && (
          <Button onClick={() => setScheduling(true)}>
            <CalendarClock aria-hidden />
            Schedule interview
          </Button>
        )}
      </div>

      {permissions.submitFeedback && (
        <Section
          id="my-interviews"
          title="My interviews"
          description={mine.list.status === "ready" && mine.list.items.length > 0 ? `${pending} waiting for your feedback.` : undefined}
          list={mine.list}
          empty="No interviews are assigned to you. They appear here when a recruiter schedules one with you."
          onRetry={mine.reload}
          onLoadMore={() => void mine.loadMore(toastProblem)}
        >
          {mine.list.items.map((interview) => (
            <InterviewRow key={interview.id} interview={interview} feedback={hasFeedback(interview)}>
              {!hasFeedback(interview) && (
                <Button size="sm" aria-label={`Give feedback for ${interview.candidate_name}`} onClick={() => setReviewing(interview)}>
                  <MessageSquarePlus aria-hidden />
                  Give feedback
                </Button>
              )}
            </InterviewRow>
          ))}
        </Section>
      )}

      {permissions.calendarSelf && <CalendarLinks api={api} />}

      {permissions.manage && (
        <Section
          id="all-interviews"
          title="All interviews"
          list={all.list}
          empty={interviewerFilter ? "No interviews for this interviewer." : "No interviews scheduled yet."}
          onRetry={all.reload}
          onLoadMore={() => void all.loadMore(toastProblem)}
          actions={
            <div className="flex items-center gap-2">
              <label htmlFor="interviews-interviewer" className="text-sm text-muted-foreground">
                Interviewer
              </label>
              <select
                id="interviews-interviewer"
                className={`${CONTROL_CLASS} w-56`}
                value={interviewerFilter}
                onChange={(event) => setInterviewerFilter(event.target.value)}
              >
                <option value="">All interviewers</option>
                {interviewers.map((interviewer) => (
                  <option key={interviewer.id} value={interviewer.id}>
                    {interviewerLabel(interviewer)}
                  </option>
                ))}
              </select>
            </div>
          }
        >
          {all.list.items.map((interview) => (
            <InterviewRow key={interview.id} interview={interview} feedback={hasFeedback(interview)} showInterviewer />
          ))}
        </Section>
      )}

      <ScheduleInterviewDialog
        api={api}
        open={scheduling}
        onOpenChange={setScheduling}
        onScheduled={({ candidateName, interviewerLabel: who }) => {
          setScheduling(false);
          toast.success(`Interview scheduled for ${candidateName} with ${who}.`);
          all.reload();
        }}
      />

      <FeedbackDialog
        api={api}
        interview={reviewing}
        onOpenChange={(open) => !open && setReviewing(null)}
        onSubmitted={(interview) => {
          markSubmitted(interview);
          setReviewing(null);
          toast.success(`Feedback for ${interview.candidate_name} submitted.`);
        }}
        onAlreadySubmitted={markSubmitted}
      />
    </div>
  );
}

function InterviewRow({
  interview,
  feedback,
  showInterviewer = false,
  children,
}: {
  interview: InterviewListItem;
  feedback: boolean;
  showInterviewer?: boolean;
  children?: ReactNode;
}) {
  return (
    <li data-interview-id={interview.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-3">
      <div className="min-w-0">
        <p className="truncate font-medium">{interview.candidate_name}</p>
        <p className="truncate text-sm text-muted-foreground">
          {interview.requisition_title}
          {showInterviewer && ` · ${interviewerLabel({ id: interview.interviewer_id, email: interview.interviewer_email })}`}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <time dateTime={interview.scheduled_at} className="text-sm tabular-nums">
          {formatDateTime(interview.scheduled_at)}
        </time>
        <Badge variant={feedback ? "secondary" : "outline"}>{feedback ? "Feedback submitted" : "Feedback pending"}</Badge>
        {children}
      </div>
    </li>
  );
}
