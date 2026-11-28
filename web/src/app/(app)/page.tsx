import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/app-shell/page-header";
import { ProblemView } from "@/components/problem/problem-view";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ROLE_LABELS } from "@/lib/actor/actor";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";
import { visibleNav } from "@/lib/nav";

export default async function OverviewPage() {
  const result = await getCurrentActor();
  if (!result.ok) return <ProblemView problem={result.problem} retryHref="/" />;
  const { actor } = result;
  const destinations = visibleNav(actor).filter((item) => item.href !== "/");
  return (
    <>
      <PageHeader
        title={`Welcome, ${actor.displayName}`}
        description={`You are signed in to ${actor.tenantName} as ${ROLE_LABELS[actor.role]}.`}
      />
      {destinations.length === 0 ? (
        <ProblemView
          problem={{
            type: `${PROBLEM_TYPE_BASE}forbidden`,
            title: "Forbidden",
            status: 403,
            detail: "Your role has no screens in the web app yet. Ask a tenant admin if you need more access.",
          }}
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {destinations.map((item) => (
            <li key={item.href}>
              <Link href={item.href} className="group block rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <Card className="h-full transition-colors group-hover:bg-muted/50">
                  <CardHeader>
                    <CardTitle role="heading" aria-level={2} className="flex items-center justify-between">
                      {item.label}
                      <ArrowRight aria-hidden className="size-4 text-muted-foreground" />
                    </CardTitle>
                    <CardDescription>{item.description}</CardDescription>
                  </CardHeader>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
