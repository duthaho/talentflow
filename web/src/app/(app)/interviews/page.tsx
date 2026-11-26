import { PageHeader } from "@/components/app-shell/page-header";
import { RequirePermission } from "@/components/app-shell/require-permission";
import { InterviewsWorkspace } from "@/components/interviews/interviews-workspace";
import { can } from "@/lib/actor/actor";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { navItem } from "@/lib/nav";

async function Workspace() {
  const result = await getCurrentActor();
  if (!result.ok) return null;
  const { actor } = result;
  return (
    <InterviewsWorkspace
      permissions={{
        manage: can(actor, "interview:manage"),
        submitFeedback: can(actor, "feedback:submit"),
        calendarSelf: can(actor, "calendar:self"),
      }}
    />
  );
}

export default async function InterviewsPage() {
  const item = navItem("/interviews");
  return (
    <RequirePermission item={item}>
      <PageHeader title={item.label} description={item.description} />
      <Workspace />
    </RequirePermission>
  );
}
