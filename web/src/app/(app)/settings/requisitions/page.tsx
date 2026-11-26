import { PageHeader } from "@/components/app-shell/page-header";
import { RequirePermission } from "@/components/app-shell/require-permission";
import { RequisitionsWorkspace } from "@/components/requisitions/requisitions-workspace";
import { can } from "@/lib/actor/actor";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { navItem } from "@/lib/nav";

export default async function RequisitionsPage() {
  const result = await getCurrentActor();
  const item = navItem("/settings/requisitions");
  return <RequirePermission item={item}>
    <PageHeader title="Requisitions" description="Choose which jobs appear on your public careers page." />
    {result.ok && <RequisitionsWorkspace canPublish={can(result.actor, "requisition:create")} />}
  </RequirePermission>;
}
