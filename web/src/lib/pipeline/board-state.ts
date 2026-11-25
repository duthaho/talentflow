import type { ProblemDetails } from "@/lib/api/problem";
import type { components } from "@/lib/api/schema";

import { isStage, STAGES, type Stage } from "./stages";

export type Candidate = components["schemas"]["CandidateListItem"];
export type CandidatePage = components["schemas"]["CandidateListResponse"];

export type Column = {
  status: "loading" | "ready" | "error";
  items: Candidate[];
  total: number;
  nextCursor: string | null;
  loadingMore: boolean;
  problem?: ProblemDetails;
};

export type Board = Record<Stage, Column>;

export type BoardAction =
  | { type: "reset" }
  | { type: "loading-more"; stage: Stage }
  | { type: "loaded"; stage: Stage; page: CandidatePage; append: boolean }
  | { type: "failed"; stage: Stage; problem: ProblemDetails }
  | { type: "moved"; from: Stage; candidate: Candidate }
  | { type: "created"; candidate: Candidate };

const LOADING: Column = { status: "loading", items: [], total: 0, nextCursor: null, loadingMore: false };

export function initialBoard(): Board {
  return Object.fromEntries(STAGES.map((stage) => [stage, LOADING])) as Board;
}

function prepend(column: Column, candidate: Candidate): Column {
  return { ...column, items: [candidate, ...column.items.filter((item) => item.id !== candidate.id)], total: column.total + 1 };
}

export function boardReducer(board: Board, action: BoardAction): Board {
  switch (action.type) {
    case "reset":
      return initialBoard();
    case "loading-more":
      return { ...board, [action.stage]: { ...board[action.stage], loadingMore: true } };
    case "loaded": {
      const column = board[action.stage];
      const seen = new Set(action.append ? column.items.map((item) => item.id) : []);
      return {
        ...board,
        [action.stage]: {
          status: "ready",
          items: [...(action.append ? column.items : []), ...action.page.items.filter((item) => !seen.has(item.id))],
          total: action.page.total,
          nextCursor: action.page.next_cursor,
          loadingMore: false,
        },
      };
    }
    case "failed":
      return board[action.stage].status === "ready"
        ? { ...board, [action.stage]: { ...board[action.stage], loadingMore: false, problem: action.problem } }
        : { ...board, [action.stage]: { ...LOADING, status: "error", problem: action.problem } };
    case "moved": {
      const source = board[action.from];
      const next = {
        ...board,
        [action.from]: { ...source, items: source.items.filter((item) => item.id !== action.candidate.id), total: Math.max(0, source.total - 1) },
      };
      return isStage(action.candidate.stage) ? { ...next, [action.candidate.stage]: prepend(next[action.candidate.stage], action.candidate) } : next;
    }
    case "created":
      return isStage(action.candidate.stage)
        ? { ...board, [action.candidate.stage]: prepend(board[action.candidate.stage], action.candidate) }
        : board;
  }
}
