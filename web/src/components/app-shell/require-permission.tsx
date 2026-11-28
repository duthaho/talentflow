import type { ReactNode } from "react";

import { ProblemView } from "@/components/problem/problem-view";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { PROBLEM_TYPE_BASE, type ProblemDetails } from "@/lib/api/problem";
import { isAllowed, type NavItem } from "@/lib/nav";

export async function RequirePermission({ item, children }: { item: NavItem; children: ReactNode }) {
  const result = await getCurrentActor();
  if (result.ok && isAllowed(item, result.actor.permissions)) return children;
  return <ProblemView problem={result.ok ? forbiddenProblem(item) : result.problem} />;
}

export function forbiddenProblem(item: Pick<NavItem, "label">): ProblemDetails {
  return {
    type: `${PROBLEM_TYPE_BASE}forbidden`,
    title: "Forbidden",
    status: 403,
    detail: `Your role cannot open ${item.label}. Ask a tenant admin if you need access.`,
  };
}
