import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell/app-shell";
import { ProblemView } from "@/components/problem/problem-view";
import { getCurrentActor } from "@/lib/actor/current-actor";

export default async function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const result = await getCurrentActor();
  if (!result.ok) {
    return (
      <main className="flex flex-1 items-center justify-center p-6">
        <ProblemView problem={result.problem} retryHref="/" />
      </main>
    );
  }
  return <AppShell actor={result.actor}>{children}</AppShell>;
}
