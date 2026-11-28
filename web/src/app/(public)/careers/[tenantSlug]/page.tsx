import Link from "next/link";
import { headers } from "next/headers";
import { publicFetch, type CareersListing } from "@/lib/careers/public-api";

export default async function CareersPage({
  params,
}: {
  params: Promise<{ tenantSlug: string }>;
}) {
  const { tenantSlug } = await params;
  const listing = await publicFetch<CareersListing>(
    tenantSlug,
    "requisitions",
    await headers(),
  );
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <p className="text-sm text-muted-foreground">Careers</p>
      <h1 className="mt-3 text-4xl font-semibold">
        Join {listing.tenant.name}
      </h1>
      <p className="mt-4 text-muted-foreground">
        Explore our open roles and send us your application.
      </p>
      <ul className="mt-10 divide-y">
        {listing.requisitions.map((job) => (
          <li key={job.id} className="py-6">
            <Link
              className="text-xl font-medium underline underline-offset-4"
              href={`/careers/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(job.id)}`}
            >
              {job.title}
            </Link>
            <p className="mt-2 text-muted-foreground">{job.department}</p>
          </li>
        ))}
      </ul>
      {!listing.requisitions.length && (
        <p className="mt-10">There are no open roles right now.</p>
      )}
    </main>
  );
}
