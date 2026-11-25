import { PageHeader } from "@/components/app-shell/page-header";
import { RequirePermission } from "@/components/app-shell/require-permission";
import { ProblemView } from "@/components/problem/problem-view";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { settle } from "@/lib/api/client";
import { serverApi } from "@/lib/api/server";
import { navItem } from "@/lib/nav";

import { RefreshTotal } from "./refresh-total";

async function CandidateSummary() {
  const api = await serverApi();
  const result = await settle(api.GET("/v1/candidate-cases", { params: { query: { limit: 1 } } }));
  if (!result.ok) return <ProblemView problem={result.problem} retryHref="/candidates" />;
  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle role="heading" aria-level={2}>
          Candidate cases
        </CardTitle>
        <CardDescription>
          {result.data.total === 0
            ? "No candidate cases yet. Cases created through the API appear here."
            : "Total candidate cases in this tenant. The pipeline board arrives in DUTH-52."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <RefreshTotal initialTotal={result.data.total} />
      </CardContent>
    </Card>
  );
}

export default function CandidatesPage() {
  const item = navItem("/candidates");
  return (
    <RequirePermission item={item}>
      <PageHeader title={item.label} description={item.description} />
      <CandidateSummary />
    </RequirePermission>
  );
}
