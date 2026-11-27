import "server-only";
import { config } from "@/lib/config";
import { clientIp } from "./client-ip";

import type { components } from "@/lib/api/schema";
export type CareersListing = components["schemas"]["PublicListing"];
export type Consent = components["schemas"]["PublicConsent"];

export async function publicFetch<T>(
  slug: string,
  resource: "requisitions" | "consent",
  headers: Pick<Headers, "get">,
): Promise<T> {
  const response = await fetch(
    `${config().apiBaseUrl}/v1/public/tenants/${encodeURIComponent(slug)}/${resource}`,
    {
      headers: { "x-forwarded-for": clientIp(headers) },
      next: { revalidate: 60 },
    },
  );
  if (!response.ok)
    throw new Error(
      response.status === 404
        ? "Careers page not found"
        : "Careers service temporarily unavailable",
    );
  return response.json() as Promise<T>;
}
