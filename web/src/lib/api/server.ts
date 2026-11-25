import "server-only";

import { getSession } from "@/lib/auth/session";
import { config } from "@/lib/config";

import { createApiClient, type ApiClient } from "./client";

export async function serverApi(): Promise<ApiClient> {
  const session = await getSession();
  return createApiClient({ baseUrl: config().apiBaseUrl, accessToken: session?.accessToken });
}
