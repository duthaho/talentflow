import "server-only";

import { cache } from "react";

import { createApiClient, settle } from "@/lib/api/client";
import { PROBLEM_TYPE_BASE, type ProblemDetails } from "@/lib/api/problem";
import type { components } from "@/lib/api/schema";
import { IdentityProviderUnavailableError } from "@/lib/auth/identity-provider";
import { requireSession } from "@/lib/auth/session";
import type { StoredSession } from "@/lib/auth/session-store";
import { config } from "@/lib/config";

import { isPermission, type Actor } from "./actor";

export type ActorResult = { ok: true; actor: Actor } | { ok: false; problem: ProblemDetails };

type CurrentActorResponse = components["schemas"]["CurrentActorResponse"];

function signInUnavailable(): ProblemDetails {
  return {
    type: `${PROBLEM_TYPE_BASE}service-unavailable`,
    title: "Service Unavailable",
    status: 503,
    detail: "The sign-in service is temporarily unavailable. Your session is kept; try again shortly.",
  };
}

export function toActor(me: CurrentActorResponse, session: Pick<StoredSession, "name" | "email">): Actor {
  const email = me.email ?? (session.email || null);
  return {
    userId: me.user_id,
    email,
    displayName: me.display_name || session.name || email || me.user_id,
    tenantId: me.tenant_id,
    tenantName: me.tenant_name,
    role: me.role,
    permissions: me.permissions.filter(isPermission),
    features: {
      webhooks: { enabled: me.features.webhooks.enabled, deliveryPaused: me.features.webhooks.delivery_paused },
    },
  };
}

export const getCurrentActor = cache(async (): Promise<ActorResult> => {
  let session;
  try {
    session = await requireSession();
  } catch (error) {
    if (!(error instanceof IdentityProviderUnavailableError)) throw error;
    return { ok: false, problem: signInUnavailable() };
  }
  const api = createApiClient({ baseUrl: config().apiBaseUrl, accessToken: session.accessToken });
  const result = await settle(api.GET("/v1/me"));
  return result.ok ? { ok: true, actor: toActor(result.data, session) } : result;
});
