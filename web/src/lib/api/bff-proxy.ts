import { PROBLEM_TYPE_BASE, type ProblemDetails } from "./problem";

const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "if-match", "if-none-match", "x-correlation-id", "idempotency-key"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "content-disposition", "etag", "retry-after", "x-correlation-id", "location"];

export type ProxyDeps = {
  apiBaseUrl: string;
  accessToken: () => Promise<string | undefined>;
  fetch?: typeof fetch;
};

function problem(status: number, slug: string, title: string, detail: string, instance: string): Response {
  const body: ProblemDetails = { type: `${PROBLEM_TYPE_BASE}${slug}`, title, status, detail, instance };
  return Response.json(body, { status, headers: { "content-type": "application/problem+json" } });
}

export function createBffProxy({ apiBaseUrl, accessToken, fetch: fetchImpl = fetch }: ProxyDeps) {
  return async function forward(request: Request, path: string[]): Promise<Response> {
    const instance = `/${path.join("/")}`;
    if (path[0] !== "v1" || path.some((segment) => segment === ".." || segment === ".")) {
      return problem(404, "not-found", "Not Found", "Only /v1 API routes are available through the web app.", instance);
    }
    const token = await accessToken();
    if (!token) {
      return problem(401, "unauthorized", "Unauthorized", "Your session has ended. Sign in again.", instance);
    }
    const target = new URL(`${apiBaseUrl}${instance.split("/").map(encodeURIComponent).join("/")}`);
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
