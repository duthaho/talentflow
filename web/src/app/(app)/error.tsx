"use client";

import { ProblemView } from "@/components/problem/problem-view";
import { fallbackProblem } from "@/lib/api/problem";

export default function AppError({ error }: { error: Error & { digest?: string } }) {
  const problem = { ...fallbackProblem(500), correlation_id: error.digest };
  return <ProblemView problem={problem} retryHref="/" />;
}
