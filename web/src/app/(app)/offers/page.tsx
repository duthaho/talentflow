import { PageHeader } from "@/components/app-shell/page-header";
import { RequirePermission } from "@/components/app-shell/require-permission";
import { OffersWorkspace } from "@/components/offers/offers-workspace";
import { can } from "@/lib/actor/actor";
import { getCurrentActor } from "@/lib/actor/current-actor";
import { navItem } from "@/lib/nav";

const OFFER_ID = /^[A-Za-z0-9-]{1,64}$/;

async function Workspace({ offer }: { offer: string | null }) {
  const result = await getCurrentActor();
  if (!result.ok) return null;
  const { actor } = result;
  return <OffersWorkspace currentUserId={actor.userId} canCreate={can(actor, "candidate:transition")} initialOfferId={offer} />;
}

export default async function OffersPage({ searchParams }: PageProps<"/offers">) {
  const { offer } = await searchParams;
  const item = navItem("/offers");
  return (
    <RequirePermission item={item}>
      <PageHeader title={item.label} description="Create offers and decide the approval steps waiting on you." />
      <Workspace offer={typeof offer === "string" && OFFER_ID.test(offer) ? offer : null} />
    </RequirePermission>
  );
}
