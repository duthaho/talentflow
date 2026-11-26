"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { PagedList } from "@/lib/offers/use-paged-list";

import type { RequisitionOption } from "./create-dialogs";
import { CONTROL_CLASS } from "./form-fields";

export function RequisitionFilter({
  list,
  options,
  value,
  onChange,
  onLoadMore,
}: {
  list: PagedList<unknown>;
  options: RequisitionOption[];
  value: string | null;
  onChange: (id: string | null) => void;
  onLoadMore: () => void;
}) {
  const remaining = list.total - list.items.length;

  return (
    <div className="grid gap-1.5" aria-busy={list.status === "loading" || list.loadingMore}>
      <label htmlFor="pipeline-requisition" className="text-sm font-medium">
        Requisition
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <select
          id="pipeline-requisition"
          aria-describedby="pipeline-requisition-status"
          className={cn(CONTROL_CLASS, "w-64")}
          value={value ?? ""}
          onChange={(event) => onChange(event.target.value || null)}
        >
          <option value="">All requisitions</option>
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        {list.status === "ready" && list.nextCursor && (
          <Button size="sm" variant="ghost" onClick={onLoadMore} disabled={list.loadingMore}>
            {list.loadingMore ? "Loading…" : `Load more requisitions (${remaining} left)`}
          </Button>
        )}
      </div>
    </div>
  );
}

export function RequisitionStatus({ list, canCreate, onRetry }: { list: PagedList<unknown>; canCreate: boolean; onRetry: () => void }) {
  return (
    <div id="pipeline-requisition-status">
      <StatusMessage list={list} canCreate={canCreate} onRetry={onRetry} />
    </div>
  );
}

function StatusMessage({ list, canCreate, onRetry }: { list: PagedList<unknown>; canCreate: boolean; onRetry: () => void }) {
  if (list.status === "loading") {
    return (
      <p className="text-xs text-muted-foreground" role="status">
        Loading requisitions…
      </p>
    );
  }
  if (list.status === "error") {
    if (list.problem?.status === 403) {
      return (
        <p className="text-xs text-muted-foreground">
          You don&apos;t have permission to list requisitions.
        </p>
      );
    }
    return (
      <div role="alert" className="flex items-center gap-2 text-xs">
        <span className="text-destructive">Couldn&apos;t load requisitions.</span>
        <Button size="xs" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      </div>
    );
  }
  if (list.total === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No requisitions yet.{canCreate ? " Create one with New requisition." : ""}
      </p>
    );
  }
  return null;
}
