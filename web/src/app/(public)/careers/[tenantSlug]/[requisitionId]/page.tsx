import { headers } from "next/headers";
import { notFound } from "next/navigation";
import {
  publicFetch,
  type CareersListing,
  type Consent,
} from "@/lib/careers/public-api";
import { ApplicationForm } from "@/components/careers/application-form";

export default async function ApplyPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; requisitionId: string }>;
}) {
  const { tenantSlug, requisitionId } = await params;
  const incoming = await headers();
  const [listing, consent] = await Promise.all([
    publicFetch<CareersListing>(tenantSlug, "requisitions", incoming),
    publicFetch<Consent>(tenantSlug, "consent", incoming),
  ]);
  const job = listing.requisitions.find((job) => job.id === requisitionId);
  if (!job) notFound();
  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <p className="text-sm text-muted-foreground">
        {listing.tenant.name} · {job.department}
      </p>
      <h1 className="mt-3 mb-8 text-3xl font-semibold">
        Apply for {job.title}
      </h1>
      <ApplicationForm
        slug={tenantSlug}
        requisitionId={requisitionId}
        consent={consent}
        policy={listing.upload_policy}
      />
    </main>
  );
}
