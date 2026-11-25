import { isSameOrigin } from "@/lib/http/same-origin";

import { PROBLEM_TYPE_BASE, type ProblemDetails } from "./problem";

const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "if-match", "if-none-match", "x-correlation-id", "idempotency-key"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "content-disposition", "etag", "retry-after", "x-correlation-id", "location"];

export type ProxyDeps = {
  apiBaseUrl: string;
  appOrigin: string;
  accessToken: () => Promise<string | undefined>;
  fetch?: typeof fetch;
};

function problem(status: number, slug: string, title: string, detail: string, instance: string): Response {
  const body: ProblemDetails = { type: `${PROBLEM_TYPE_BASE}${slug}`, title, status, detail, instance };
  return Response.json(body, { status, headers: { "content-type": "application/problem+json" } });
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function isUnsafeSegment(segment: string): boolean {
  return segment === "" || segment === "." || segment === ".." || /[/\\]/.test(segment);
}

export function createBffProxy({ apiBaseUrl, appOrigin, accessToken, fetch: fetchImpl = fetch }: ProxyDeps) {
  const apiPrefix = `${new URL(apiBaseUrl).pathname.replace(/\/+$/, "")}/v1/`;
  return async function forward(request: Request, path: string[]): Promise<Response> {
    const instance = `/${path.join("/")}`;
    const target = new URL(`${apiBaseUrl}/${path.map(encodeURIComponent).join("/")}`);
    if (path[0] !== "v1" || path.some(isUnsafeSegment) || !target.pathname.startsWith(apiPrefix)) {
      return problem(404, "not-found", "Not Found", "Only /v1 API routes are available through the web app.", instance);
    }
    if (!SAFE_METHODS.has(request.method) && !isSameOrigin(request, appOrigin)) {
      return problem(403, "forbidden", "Forbidden", "Cross-origin requests are not allowed.", instance);
    }
    let token: string | undefined;
    try {
      token = await accessToken();
    } catch {
      return problem(503, "service-unavailable", "Service Unavailable", "Sign-in service is temporarily unavailable. Try again shortly.", instance);
    }
    if (!token) {
      return problem(401, "unauthorized", "Unauthorized", "Your session has ended. Sign in again.", instance);
    }
    target.search = new URL(request.url).search;
    const headers = new Headers({ authorization: `Bearer ${token}` });
    for (const name of FORWARDED_REQUEST_HEADERS) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    const hasBody = request.method !== "GET" && request.method !== "HEAD";
    let upstream: Response;
    try {
      upstream = await fetchImpl(target, {
        method: request.method,
        headers,
        body: hasBody ? await request.arrayBuffer() : undefined,
        redirect: "manual",
        cache: "no-store",
      });
    } catch {
      return problem(503, "service-unavailable", "Service Unavailable", "The TalentFlow API could not be reached.", instance);
    }
    const responseHeaders = new Headers();
    for (const name of FORWARDED_RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  };
}
