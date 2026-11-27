import { PageHeader } from "@/components/app-shell/page-header";
import { RequirePermission } from "@/components/app-shell/require-permission";
import { WebhooksWorkspace } from "@/components/webhooks/webhooks-workspace";
import { navItem } from "@/lib/nav";

export default async function WebhooksPage() {
  return <RequirePermission item={navItem("/settings/webhooks")}>
    <PageHeader title="Webhooks" description="Send signed hiring events to your own systems, and inspect or redeliver what was sent." />
    <WebhooksWorkspace />
  </RequirePermission>;
}
