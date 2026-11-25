import type { ReactNode } from "react";

import { ProblemView } from "@/components/problem/problem-view";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import { isAllowed, type NavItem } from "@/lib/nav";

export async function RequirePermission({ item, children }: { item: NavItem; children: ReactNode }) {
  const result = await getCurrentActor();
  if (result.ok && isAllowed(item, result.actor.permissions)) return children;
  const problem = result.ok
    ? {
        type: `${PROBLEM_TYPE_BASE}forbidden`,
        title: "Forbidden",
        status: 403,
        detail: `Your role cannot open ${item.label}. Ask a tenant admin if you need access.`,
      }
    : result.problem;
  return <ProblemView problem={problem} />;
}
