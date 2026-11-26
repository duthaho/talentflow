"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiResult } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";

export type Resource<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; problem: ProblemDetails };

export function useResource<T>(load: () => Promise<ApiResult<T>>) {
  const [state, setState] = useState<Resource<T>>({ status: "loading" });
  const [reloads, setReloads] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    const run = ++generation.current;
    void load().then((result) => {
      if (run !== generation.current) return;
      setState(result.ok ? { status: "ready", data: result.data } : { status: "error", problem: result.problem });
    });
  }, [load, reloads]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setReloads((count) => count + 1);
  }, []);

  return { state, reload };
}
