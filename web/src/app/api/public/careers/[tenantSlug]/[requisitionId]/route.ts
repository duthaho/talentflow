import { config } from "@/lib/config";
import { forwardApplication } from "@/lib/careers/apply-proxy";

export async function POST(
  request: Request,
  {
    params,
  }: { params: Promise<{ tenantSlug: string; requisitionId: string }> },
) {
  const { tenantSlug, requisitionId } = await params;
  return forwardApplication(request, tenantSlug, requisitionId, {
    apiBaseUrl: config().apiBaseUrl,
    appOrigin: config().appBaseUrl,
    maxBytes: Number(process.env.ATTACHMENT_MAX_BYTES ?? "5242880"),
  });
}
