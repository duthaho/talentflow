"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiResult } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";

export type Page<T> = { items: T[]; next_cursor?: string | null; total?: number };

export type PagedList<T> = {
  status: "loading" | "ready" | "error";
  items: T[];
  total: number;
  nextCursor: string | null;
  loadingMore: boolean;
  problem?: ProblemDetails;
};

const LOADING: PagedList<never> = { status: "loading", items: [], total: 0, nextCursor: null, loadingMore: false };

export function usePagedList<T extends { id: string }>(fetchPage: (cursor: string | null) => Promise<ApiResult<Page<T>>>) {
  const [list, setList] = useState<PagedList<T>>(LOADING);
  const [reloads, setReloads] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    const run = ++generation.current;
    void fetchPage(null).then((result) => {
      if (run !== generation.current) return;
      setList(
        result.ok
          ? {
              status: "ready",
              items: result.data.items,
              total: result.data.total ?? result.data.items.length,
              nextCursor: result.data.next_cursor ?? null,
              loadingMore: false,
            }
          : { ...LOADING, status: "error", problem: result.problem },
      );
    });
  }, [fetchPage, reloads]);

  const reload = useCallback(() => {
    setList(LOADING);
    setReloads((count) => count + 1);
  }, []);

  const loadMore = useCallback(
    async (onError: (problem: ProblemDetails) => void) => {
      if (list.status !== "ready" || !list.nextCursor || list.loadingMore) return;
      const run = generation.current;
      setList((current) => ({ ...current, loadingMore: true }));
      const result = await fetchPage(list.nextCursor);
      if (run !== generation.current) return;
      if (result.ok) {
        setList((current) => {
          const seen = new Set(current.items.map((item) => item.id));
          return {
            status: "ready",
            items: [...current.items, ...result.data.items.filter((item) => !seen.has(item.id))],
            total: result.data.total ?? current.total,
            nextCursor: result.data.next_cursor ?? null,
            loadingMore: false,
          };
        });
      } else {
        setList((current) => ({ ...current, loadingMore: false }));
        onError(result.problem);
      }
    },
    [fetchPage, list],
  );

  const remove = useCallback((id: string) => {
    setList((current) =>
      current.items.some((item) => item.id === id)
        ? { ...current, items: current.items.filter((item) => item.id !== id), total: Math.max(0, current.total - 1) }
        : current,
    );
  }, []);

  return { list, reload, loadMore, remove };
}
