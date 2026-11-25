import { PageHeader } from "@/components/app-shell/page-header";
import { RequirePermission } from "@/components/app-shell/require-permission";
import { PipelineBoard } from "@/components/pipeline/pipeline-board";
import { can } from "@/lib/actor/actor";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { navItem } from "@/lib/nav";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function Board({ requisition }: { requisition: string | null }) {
  const result = await getCurrentActor();
  if (!result.ok) return null;
  const { actor } = result;
  return (
    <PipelineBoard
      initialRequisitionId={requisition}
      permissions={{
        transition: can(actor, "candidate:transition"),
        createCandidate: can(actor, "candidate:create"),
        createRequisition: can(actor, "requisition:create"),
      }}
    />
  );
}

export default async function CandidatesPage({ searchParams }: PageProps<"/candidates">) {
  const { requisition } = await searchParams;
  const item = navItem("/candidates");
  return (
    <RequirePermission item={item}>
      <PageHeader title={item.label} description="Drag a candidate to the next stage, or use its Move to menu." />
      <Board requisition={typeof requisition === "string" && UUID.test(requisition) ? requisition : null} />
    </RequirePermission>
  );
}
