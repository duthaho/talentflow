import { notFound } from "next/navigation";

import { RequirePermission } from "@/components/app-shell/require-permission";
import { CandidateDetail } from "@/components/candidate-detail/candidate-detail";
import { can } from "@/lib/actor/actor";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { navItem } from "@/lib/nav";

const CASE_ID = /^[A-Za-z0-9-]{1,64}$/;

async function Detail({ candidateCaseId }: { candidateCaseId: string }) {
  const result = await getCurrentActor();
  if (!result.ok) return null;
  const { actor } = result;
  return (
    <CandidateDetail
      candidateCaseId={candidateCaseId}
      currentUserId={actor.userId}
      permissions={{
        attachments: can(actor, "candidate:attachment"),
        audit: can(actor, "audit:read"),
        retention: can(actor, "retention:manage"),
      }}
    />
  );
}

export default async function CandidateDetailPage({ params }: PageProps<"/candidates/[candidateCaseId]">) {
  const { candidateCaseId } = await params;
  if (!CASE_ID.test(candidateCaseId)) notFound();
  return (
    <RequirePermission item={navItem("/candidates")}>
      <Detail candidateCaseId={candidateCaseId} />
    </RequirePermission>
  );
}
