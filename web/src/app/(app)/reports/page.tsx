import { PageHeader } from "@/components/app-shell/page-header";
import { RequirePermission } from "@/components/app-shell/require-permission";
import { PipelineReportView } from "@/components/reports/pipeline-report-view";
import { settle } from "@/lib/api/client";
import { serverApi } from "@/lib/api/server";
import { navItem } from "@/lib/nav";

async function Report() {
  const api = await serverApi();
  const result = await settle(api.GET("/v1/reports/pipeline"));
  return <PipelineReportView result={result} />;
}

export default async function ReportsPage() {
  const item = navItem("/reports");
  return (
    <RequirePermission item={item}>
      <PageHeader title={item.label} description="Aggregate pipeline counts for your tenant. No candidate details are shown." />
      <Report />
    </RequirePermission>
  );
}
