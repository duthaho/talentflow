import "server-only";
import { isSameOrigin } from "@/lib/http/same-origin";
import { clientIp } from "./client-ip";

function problem(status: number, detail: string): Response {
  return Response.json(
    { status, detail },
    { status, headers: { "content-type": "application/problem+json" } },
  );
}

export async function forwardApplication(
  request: Request,
  slug: string,
  requisitionId: string,
  deps: {
    apiBaseUrl: string;
    appOrigin: string;
    maxBytes: number;
    fetch?: typeof fetch;
  },
): Promise<Response> {
  if (!isSameOrigin(request, deps.appOrigin))
    return problem(403, "Cross-origin applications are not allowed");
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("multipart/form-data;"))
    return problem(422, "Choose a CV and complete the application form");
  const cap = deps.maxBytes + 65536;
  const length = request.headers.get("content-length");
  if (length && (!/^\d+$/.test(length) || Number(length) > cap))
    return problem(413, "Application is too large");
  let ip: string;
  try {
    ip = clientIp(request.headers);
  } catch {
    return problem(503, "Application service temporarily unavailable");
  }
  const reader = request.body?.getReader();
  if (!reader) return problem(422, "Application form is required");
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > cap) {
        await reader.cancel();
        return problem(413, "Application is too large");
      }
      chunks.push(value);
    }
  } catch {
    return problem(422, "Application upload was interrupted");
  } finally {
    reader.releaseLock();
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const headers = new Headers({
    "content-type": contentType,
    "content-length": String(size),
    "x-forwarded-for": ip,
  });
  const correlation = request.headers.get("x-correlation-id");
  if (correlation) headers.set("x-correlation-id", correlation);
  try {
    const response = await (deps.fetch ?? fetch)(
      `${deps.apiBaseUrl}/v1/public/tenants/${encodeURIComponent(slug)}/requisitions/${encodeURIComponent(requisitionId)}/applications`,
      {
        method: "POST",
        headers,
        body,
        redirect: "manual",
        cache: "no-store",
      },
    );
    const outgoing = new Headers();
    for (const name of ["content-type", "retry-after"]) {
      const value = response.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    return new Response(response.body, {
      status: response.status,
      headers: outgoing,
    });
  } catch {
    return problem(503, "Application service temporarily unavailable");
  }
}
