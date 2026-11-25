import createClient from "openapi-fetch";

import { fallbackProblem, toProblem, type ProblemDetails } from "./problem";
import type { paths } from "./schema";

export type ApiClient = ReturnType<typeof createClient<paths>>;

export type ApiResult<T> = { ok: true; data: T } | { ok: false; problem: ProblemDetails };

export function createApiClient(options: {
  baseUrl: string;
  accessToken?: string;
  fetch?: typeof fetch;
}): ApiClient {
  return createClient<paths>({
    baseUrl: options.baseUrl,
    headers: options.accessToken ? { Authorization: `Bearer ${options.accessToken}` } : {},
    fetch: options.fetch,
  });
}

export const BROWSER_API_BASE = "/api/tf";

export function browserApi(): ApiClient {
  return createApiClient({ baseUrl: BROWSER_API_BASE });
}

export async function settle<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<ApiResult<T>> {
  try {
    const { data, error, response } = await call;
    if (response.ok) return { ok: true, data: data as T };
    return { ok: false, problem: toProblem(response.status, error) };
  } catch {
    return { ok: false, problem: fallbackProblem(0) };
  }
}
