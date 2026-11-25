"use client";

import { RefreshCw } from "lucide-react";
import { useState, useTransition } from "react";

import { toastProblem } from "@/components/problem/toast-problem";
import { Button } from "@/components/ui/button";
import { browserApi, settle } from "@/lib/api/client";

export function RefreshTotal({ initialTotal }: { initialTotal: number }) {
  const [total, setTotal] = useState(initialTotal);
  const [pending, startTransition] = useTransition();

  function refresh() {
    startTransition(async () => {
      const result = await settle(browserApi().GET("/v1/candidate-cases", { params: { query: { limit: 1 } } }));
      if (result.ok) setTotal(result.data.total);
      else toastProblem(result.problem);
    });
  }

  return (
    <div className="flex items-center gap-4">
      <p className="text-3xl font-semibold tabular-nums" aria-live="polite">
        {total}
        <span className="sr-only"> candidate cases</span>
      </p>
      <Button variant="outline" size="sm" onClick={refresh} disabled={pending}>
        <RefreshCw aria-hidden className={pending ? "animate-spin" : undefined} />
        Refresh
      </Button>
    </div>
  );
}
