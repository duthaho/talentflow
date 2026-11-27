import { forbidden } from "next/navigation";

import { PageHeader } from "@/components/app-shell/page-header";
import { RequirePermission } from "@/components/app-shell/require-permission";
import { WebhooksWorkspace } from "@/components/webhooks/webhooks-workspace";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { isAllowed, navItem } from "@/lib/nav";

export default async function WebhooksPage() {
  const item = navItem("/settings/webhooks");
  const result = await getCurrentActor();
  if (result.ok && !isAllowed(item, result.actor.permissions)) forbidden();
  return <RequirePermission item={item}>
    <PageHeader title="Webhooks" description="Send signed hiring events to your own systems, and inspect or redeliver what was sent." />
    <WebhooksWorkspace />
  </RequirePermission>;
}
