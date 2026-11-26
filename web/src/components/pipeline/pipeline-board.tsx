"use client";

import { LoaderCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type DragEvent } from "react";
import { toast } from "sonner";

import { ProblemView } from "@/components/problem/problem-view";
import { toastProblem } from "@/components/problem/toast-problem";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi, settle, type ApiClient, type ApiResult } from "@/lib/api/client";
import { usePagedList } from "@/lib/offers/use-paged-list";
import { boardReducer, initialBoard, type Candidate, type CandidatePage, type Column } from "@/lib/pipeline/board-state";
import { GENERIC_STAGE_TRANSITIONS, canMove, isStage, STAGE_LABELS, STAGES, type Stage } from "@/lib/pipeline/stages";

import { NewCandidateDialog, NewRequisitionDialog, type RequisitionOption } from "./create-dialogs";
import { CONTROL_CLASS } from "./form-fields";
import { RequisitionFilter, RequisitionStatus } from "./requisition-filter";

export const PAGE_SIZE = 20;
export const REQUISITION_PAGE_SIZE = 100;

export type BoardPermissions = { transition: boolean; createCandidate: boolean; createRequisition: boolean };

function fullName(candidate: Candidate): string {
  return `${candidate.first_name} ${candidate.last_name}`;
}

function shortLabel(id: string): string {
  return `Requisition ${id.slice(0, 8)}`;
}

export function PipelineBoard({
  initialRequisitionId,
  permissions,
  api: injectedApi,
}: {
  initialRequisitionId: string | null;
  permissions: BoardPermissions;
  api?: ApiClient;
}) {
  const api = useMemo(() => injectedApi ?? browserApi(), [injectedApi]);
  const [requisitionId, setRequisitionId] = useState(initialRequisitionId);
  const [createdRequisitions, setCreatedRequisitions] = useState<readonly RequisitionOption[]>([]);
  const requisitionList = usePagedList(
    useCallback(
      (cursor: string | null) =>
        settle(api.GET("/v1/requisitions", { params: { query: { cursor: cursor ?? undefined, limit: REQUISITION_PAGE_SIZE } } })),
      [api],
    ),
  );
  const [board, dispatch] = useReducer(boardReducer, undefined, initialBoard);
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [dragging, setDragging] = useState<Candidate | null>(null);
  const [conflict, setConflict] = useState<Candidate | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [reloads, setReloads] = useState(0);
  const generation = useRef(0);

  const fetchColumn = useCallback(
    (stage: Stage, cursor: string | null) =>
      settle(
        api.GET("/v1/candidate-cases", {
          params: { query: { stage, requisition_id: requisitionId ?? undefined, cursor: cursor ?? undefined, limit: PAGE_SIZE } },
        }),
      ),
    [api, requisitionId],
  );

  const applyColumn = useCallback(
    (stage: Stage, cursor: string | null, run: number, result: ApiResult<CandidatePage>) => {
      if (run !== generation.current) return;
      if (result.ok) {
        dispatch({ type: "loaded", stage, page: result.data, append: cursor !== null });
      } else {
        dispatch({ type: "failed", stage, problem: result.problem });
        if (cursor !== null) toastProblem(result.problem);
      }
    },
    [],
  );

  function loadColumn(stage: Stage, cursor: string | null) {
    const run = generation.current;
    void fetchColumn(stage, cursor).then((result) => applyColumn(stage, cursor, run, result));
  }

  useEffect(() => {
    const run = ++generation.current;
    for (const stage of STAGES) void fetchColumn(stage, null).then((result) => applyColumn(stage, null, run, result));
  }, [fetchColumn, applyColumn, reloads]);

  function refresh() {
    dispatch({ type: "reset" });
    setReloads((count) => count + 1);
  }

  function selectRequisition(id: string | null) {
    if (id === requisitionId) return;
    setRequisitionId(id);
    dispatch({ type: "reset" });
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("requisition", id);
    else url.searchParams.delete("requisition");
    window.history.replaceState(null, "", url);
  }

  async function move(candidate: Candidate, target: Stage) {
    if (!permissions.transition || !isStage(candidate.stage) || !canMove(candidate.stage, target) || pending.has(candidate.id)) return;
    const from = candidate.stage;
    setPending((current) => new Set(current).add(candidate.id));
    const result = await settle(
      api.PATCH("/v1/candidate-cases/{candidate_case_id}/stage", {
        params: { path: { candidate_case_id: candidate.id } },
        body: { target_stage: target, expected_version: candidate.version },
      }),
    );
    setPending((current) => {
      const next = new Set(current);
      next.delete(candidate.id);
      return next;
    });
    if (result.ok) {
      dispatch({ type: "moved", from, candidate: result.data });
      setAnnouncement(`${fullName(candidate)} moved to ${STAGE_LABELS[target]}.`);
    } else if (result.problem.status === 409) {
      setConflict(candidate);
    } else {
      toastProblem(result.problem);
    }
  }

  function resolveConflict() {
    setConflict(null);
    refresh();
  }

  const requisitionTitles = new Map<string, string>([
    ...requisitionList.list.items.map((item): [string, string] => [item.id, item.title]),
    ...createdRequisitions.map((item): [string, string] => [item.id, item.label]),
  ]);
  if (requisitionId && !requisitionTitles.has(requisitionId)) requisitionTitles.set(requisitionId, shortLabel(requisitionId));
  const requisitions: RequisitionOption[] = [...requisitionTitles].map(([id, label]) => ({ id, label }));
  const columns = STAGES.map((stage) => [stage, board[stage]] as const);
  const allFailed = columns.every(([, column]) => column.status === "error");
  const emptyBoard = columns.every(([, column]) => column.status === "ready" && column.total === 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <RequisitionFilter
          list={requisitionList.list}
          options={requisitions}
          value={requisitionId}
          onChange={selectRequisition}
          onLoadMore={() => void requisitionList.loadMore(toastProblem)}
        />
        <Button variant="outline" onClick={refresh}>
          <RefreshCw aria-hidden />
          Refresh
        </Button>
        <div className="ml-auto flex flex-wrap gap-2">
          {permissions.createRequisition && (
            <NewRequisitionDialog
              api={api}
              onCreated={(requisition) => {
                setCreatedRequisitions((current) => [...current, { id: requisition.id, label: requisition.title }]);
                selectRequisition(requisition.id);
                toast.success(`Requisition "${requisition.title}" created.`);
              }}
            />
          )}
          {permissions.createCandidate && (
            <NewCandidateDialog
              api={api}
              requisitions={requisitions}
              defaultRequisitionId={requisitionId}
              onCreated={(candidate) => {
                if (!requisitionId || requisitionId === candidate.requisition_id) dispatch({ type: "created", candidate });
                toast.success(`${fullName(candidate)} added to Applied.`);
              }}
            />
          )}
        </div>
      </div>

      <RequisitionStatus list={requisitionList.list} canCreate={permissions.createRequisition} onRetry={requisitionList.reload} />

      {!permissions.transition && (
        <p className="text-sm text-muted-foreground">Read-only: your role can view the pipeline but cannot move candidates.</p>
      )}
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>

      {allFailed ? (
        <ProblemView problem={board.applied.problem!} retryHref={requisitionId ? `/candidates?requisition=${requisitionId}` : "/candidates"} />
      ) : (
        <>
          {emptyBoard && (
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              No candidates {requisitionId ? "in this requisition" : "yet"}.{" "}
              {permissions.createCandidate ? "Add the first one with New candidate." : "Candidates appear here once a recruiter adds them."}
            </p>
          )}
          <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-4 md:-mx-6 md:px-6" aria-label="Pipeline board">
            {columns.map(([stage, column]) => (
              <StageColumn
                key={stage}
                stage={stage}
                column={column}
                dragging={dragging}
                pending={pending}
                canTransition={permissions.transition}
                showRequisition={!requisitionId}
                requisitionLabel={(id) => requisitionTitles.get(id) ?? shortLabel(id)}
                onDragStart={setDragging}
                onDragEnd={() => setDragging(null)}
                onMove={(candidate, target) => {
                  setDragging(null);
                  void move(candidate, target);
                }}
                onRetry={() => loadColumn(stage, null)}
                onLoadMore={() => {
                  dispatch({ type: "loading-more", stage });
                  loadColumn(stage, column.nextCursor);
                }}
              />
            ))}
          </div>
        </>
      )}

      <Dialog open={conflict !== null} onOpenChange={(open) => !open && resolveConflict()}>
        <DialogContent role="alertdialog" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Changed by someone else</DialogTitle>
            <DialogDescription>
              {conflict ? `${fullName(conflict)} was updated by someone else after this board loaded. ` : ""}
              Your move was not applied. Refresh to see the latest stage, then try again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={resolveConflict} autoFocus>
              <RefreshCw aria-hidden />
              Refresh board
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StageColumn({
  stage,
  column,
  dragging,
  pending,
  canTransition,
  showRequisition,
  requisitionLabel,
  onDragStart,
  onDragEnd,
  onMove,
  onRetry,
  onLoadMore,
}: {
  stage: Stage;
  column: Column;
  dragging: Candidate | null;
  pending: ReadonlySet<string>;
  canTransition: boolean;
  showRequisition: boolean;
  requisitionLabel: (id: string) => string;
  onDragStart: (candidate: Candidate) => void;
  onDragEnd: () => void;
  onMove: (candidate: Candidate, target: Stage) => void;
  onRetry: () => void;
  onLoadMore: () => void;
}) {
  const headingId = `stage-${stage}`;
  const droppable = dragging !== null && canMove(dragging.stage, stage);
  const dimmed = dragging !== null && !droppable && dragging.stage !== stage;

  const dropHandlers = droppable
    ? {
        onDragOver: (event: DragEvent) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
        },
        onDrop: (event: DragEvent) => {
          event.preventDefault();
          onMove(dragging, stage);
        },
      }
    : {};

  return (
    <section
      aria-labelledby={headingId}
      aria-busy={column.status === "loading" || column.loadingMore}
      data-stage={stage}
      data-droppable={droppable || undefined}
      className={`flex w-64 shrink-0 snap-start flex-col rounded-xl border bg-muted/40 transition-opacity ${
        droppable ? "border-dashed border-primary bg-primary/5" : ""
      } ${dimmed ? "opacity-50" : ""}`}
      {...dropHandlers}
    >
      <header className="flex items-center justify-between gap-2 px-3 pt-3 pb-2">
        <h2 id={headingId} className="text-sm font-medium">
          {STAGE_LABELS[stage]}
        </h2>
        {column.status === "ready" && (
          <Badge variant="secondary" aria-label={`${column.total} candidates`}>
            {column.total}
          </Badge>
        )}
      </header>
      <div className="flex flex-1 flex-col gap-2 px-2 pb-3">
        {column.status === "loading" && (
          <>
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </>
        )}
        {column.status === "error" && (
          <div role="alert" className="space-y-2 px-1 text-sm">
            <p className="text-destructive">Couldn&apos;t load this stage.</p>
            <Button size="sm" variant="outline" onClick={onRetry}>
              Retry
            </Button>
          </div>
        )}
        {column.status === "ready" && column.items.length === 0 && <p className="px-1 text-sm text-muted-foreground">No candidates</p>}
        {column.items.length > 0 && (
          <ul className="flex flex-col gap-2">
            {column.items.map((candidate) => (
              <CandidateCard
                key={candidate.id}
                candidate={candidate}
                pending={pending.has(candidate.id)}
                canTransition={canTransition}
                requisition={showRequisition ? requisitionLabel(candidate.requisition_id) : null}
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
                onMove={onMove}
              />
            ))}
          </ul>
        )}
        {column.status === "ready" && column.nextCursor && (
          <Button size="sm" variant="ghost" onClick={onLoadMore} disabled={column.loadingMore}>
            {column.loadingMore ? "Loading…" : `Load more (${column.total - column.items.length} left)`}
          </Button>
        )}
      </div>
    </section>
  );
}

function CandidateCard({
  candidate,
  pending,
  canTransition,
  requisition,
  onDragStart,
  onDragEnd,
  onMove,
}: {
  candidate: Candidate;
  pending: boolean;
  canTransition: boolean;
  requisition: string | null;
  onDragStart: (candidate: Candidate) => void;
  onDragEnd: () => void;
  onMove: (candidate: Candidate, target: Stage) => void;
}) {
  const targets = canTransition && isStage(candidate.stage) ? GENERIC_STAGE_TRANSITIONS[candidate.stage] : [];
  const movable = targets.length > 0 && !pending;
  const name = fullName(candidate);
  const selectId = `move-${candidate.id}`;

  return (
    <li
      draggable={movable}
      aria-busy={pending}
      data-candidate-id={candidate.id}
      onDragStart={
        movable
          ? (event) => {
              event.dataTransfer.effectAllowed = "move";
              event.dataTransfer.setData("text/plain", candidate.id);
              onDragStart(candidate);
            }
          : undefined
      }
      onDragEnd={onDragEnd}
      className={`space-y-1 rounded-lg border bg-card p-3 text-sm shadow-xs ${movable ? "cursor-grab active:cursor-grabbing" : ""} ${
        pending ? "opacity-60" : ""
      }`}
    >
      <p className="flex items-center gap-1.5 font-medium">
        {name}
        {pending && <LoaderCircle aria-label="Moving" className="size-3.5 animate-spin" />}
      </p>
      <p className="truncate text-xs text-muted-foreground">{candidate.email}</p>
      {requisition && <p className="truncate text-xs text-muted-foreground">{requisition}</p>}
      {targets.length > 0 && (
        <>
          <label htmlFor={selectId} className="sr-only">
            Move {name} to stage
          </label>
          <select
            id={selectId}
            value=""
            disabled={pending}
            className={`${CONTROL_CLASS} mt-1 h-7 text-xs`}
            onChange={(event) => {
              if (isStage(event.target.value)) onMove(candidate, event.target.value);
            }}
          >
            <option value="">Move to…</option>
            {targets.map((target) => (
              <option key={target} value={target}>
                {STAGE_LABELS[target]}
              </option>
            ))}
          </select>
        </>
      )}
    </li>
  );
}
