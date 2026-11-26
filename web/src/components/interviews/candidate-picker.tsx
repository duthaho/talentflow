"use client";

import { useEffect, useId, useState, type KeyboardEvent } from "react";

import { CONTROL_CLASS, FormProblem } from "@/components/pipeline/form-fields";
import { Button } from "@/components/ui/button";
import { settle, type ApiResult } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";
import type { CandidateCase, InterviewsApi } from "@/lib/interviews/contract";

export const SCHEDULABLE_STAGES = ["screening", "interviewing"] as const;
export const PICKER_LIMIT = 20;
export const SEARCH_DEBOUNCE_MS = 300;
const MIN_TERM_LENGTH = 2;
const MAX_TERM_LENGTH = 100;

export type CandidateResults = { candidates: CandidateCase[]; total: number };

type Search =
  | { status: "loading"; term: string }
  | { status: "error"; term: string; problem: ProblemDetails }
  | { status: "ready"; term: string; results: CandidateResults };

const STAGE_LABELS: Record<string, string> = { screening: "Screening", interviewing: "Interviewing" };

export function fullName(candidate: CandidateCase): string {
  return `${candidate.first_name} ${candidate.last_name}`;
}

export async function findCandidates(api: InterviewsApi, term?: string, signal?: AbortSignal): Promise<ApiResult<CandidateResults>> {
  const stages = await Promise.all(
    SCHEDULABLE_STAGES.map((stage) =>
      settle(api.GET("/v1/candidate-cases", { params: { query: { stage, limit: PICKER_LIMIT, ...(term ? { q: term } : {}) } }, signal })),
    ),
  );
  const candidates: CandidateCase[] = [];
  let total = 0;
  for (const result of stages) {
    if (!result.ok) return result;
    candidates.push(...result.data.items);
    total += result.data.total;
  }
  candidates.sort((a, b) => fullName(a).localeCompare(fullName(b)));
  return { ok: true, data: { candidates, total } };
}

function useCandidateSearch(api: InterviewsApi, term: string, initial: CandidateResults): { search: Search; retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [fetched, setFetched] = useState<{ term: string; attempt: number; result: ApiResult<CandidateResults> } | null>(null);
  const searching = term.length >= MIN_TERM_LENGTH;

  useEffect(() => {
    if (!searching) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void findCandidates(api, term, controller.signal).then((result) => {
        if (!controller.signal.aborted) setFetched({ term, attempt, result });
      });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [api, term, searching, attempt]);

  const retry = () => setAttempt((count) => count + 1);
  if (!searching) return { search: { status: "ready", term: "", results: initial }, retry };
  if (fetched?.term !== term || fetched.attempt !== attempt) return { search: { status: "loading", term }, retry };
  const { result } = fetched;
  return { search: result.ok ? { status: "ready", term, results: result.data } : { status: "error", term, problem: result.problem }, retry };
}

function announcement(search: Search): string {
  if (search.status === "loading") return "Searching…";
  if (search.status === "error") return "Search failed.";
  const { candidates, total } = search.results;
  if (candidates.length === 0) return `No candidates in Screening or Interviewing match '${search.term}'.`;
  if (total > candidates.length) return `Showing ${candidates.length} of ${total}. ${search.term ? "Type more to narrow the list." : "Type to search."}`;
  return candidates.length === 1 ? "1 candidate." : `${candidates.length} candidates.`;
}

export function CandidatePicker({
  api,
  initial,
  selected,
  onSelect,
  error,
}: {
  api: InterviewsApi;
  initial: CandidateResults;
  selected: CandidateCase | null;
  onSelect: (candidate: CandidateCase) => void;
  error?: string;
}) {
  const id = useId();
  const inputId = `${id}-search`;
  const listId = `${id}-list`;
  const errorId = `${id}-error`;
  const [text, setText] = useState("");
  const [active, setActive] = useState(-1);
  const { search, retry } = useCandidateSearch(api, text.trim(), initial);
  const options = search.status === "ready" ? search.results.candidates : [];
  const activeOption = options[active];

  function choose(candidate: CandidateCase) {
    onSelect(candidate);
    setActive(options.indexOf(candidate));
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (options.length === 0) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((index) => (index + step + options.length) % options.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (activeOption) choose(activeOption);
    } else if (event.key === "Escape" && text) {
      setText("");
      setActive(-1);
    }
  }

  return (
    <div className="grid gap-1.5">
      <label htmlFor={inputId} className="text-sm font-medium">
        Candidate
      </label>
      <input
        id={inputId}
        type="search"
        role="combobox"
        autoComplete="off"
        placeholder="Search by name or email"
        maxLength={MAX_TERM_LENGTH}
        data-clear-on-escape
        aria-expanded={options.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={activeOption ? `${listId}-${activeOption.id}` : undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className={CONTROL_CLASS}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setActive(-1);
        }}
        onKeyDown={onKeyDown}
      />
      <p role="status" aria-live="polite" className="text-xs text-muted-foreground">
        {announcement(search)}
      </p>
      {search.status === "loading" && <div aria-busy="true" className="h-1 animate-pulse rounded bg-muted" />}
      {search.status === "error" && (
        <div className="space-y-2">
          <FormProblem problem={search.problem} />
          <Button type="button" variant="outline" size="sm" onClick={retry}>
            Retry
          </Button>
        </div>
      )}
      <ul id={listId} role="listbox" aria-label="Candidates" className="max-h-48 overflow-y-auto rounded-lg border empty:hidden">
        {options.map((candidate, index) => (
          <li
            key={candidate.id}
            id={`${listId}-${candidate.id}`}
            role="option"
            aria-selected={candidate.id === selected?.id}
            className={`cursor-pointer px-2.5 py-1.5 aria-selected:bg-accent aria-selected:font-medium ${index === active ? "outline-2 -outline-offset-2 outline-ring" : ""}`}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => choose(candidate)}
          >
            <span className="block">{fullName(candidate)}</span>
            <span className="block text-xs text-muted-foreground">
              {candidate.email} · {STAGE_LABELS[candidate.stage] ?? candidate.stage}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs">
        {selected ? `Selected: ${fullName(selected)} (${selected.email})` : "No candidate selected."}
      </p>
      {error && (
        <p id={errorId} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
