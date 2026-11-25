import "server-only";

import { cache } from "react";

import { fallbackProblem, toProblem, type ProblemDetails } from "@/lib/api/problem";
import { requireSession } from "@/lib/auth/session";
import { config } from "@/lib/config";

import type { Actor, Permission, Role } from "./actor";
import { mockActor } from "./mock";

type MeResponse = {
  user_id: string;
  email: string;
  display_name?: string;
  tenant_id: string;
  tenant_name: string;
  role: Role | null;
  permissions: Permission[];
};

export type ActorResult = { ok: true; actor: Actor } | { ok: false; problem: ProblemDetails };

export const getCurrentActor = cache(async (): Promise<ActorResult> => {
  const session = await requireSession();
  if (config().actorSource === "mock") {
    return { ok: true, actor: mockActor(session) };
  }
  try {
    const response = await fetch(`${config().apiBaseUrl}/v1/me`, {
      headers: { Authorization: `Bearer ${session.accessToken}` },
      cache: "no-store",
    });
    const body: unknown = await response.json().catch(() => undefined);
    if (!response.ok) return { ok: false, problem: toProblem(response.status, body) };
    const me = body as MeResponse;
    return {
      ok: true,
      actor: {
        userId: me.user_id,
        email: me.email,
        displayName: me.display_name || session.name || me.email,
        tenantId: me.tenant_id,
        tenantName: me.tenant_name,
        role: me.role,
        permissions: me.permissions,
      },
    };
  } catch {
    return { ok: false, problem: fallbackProblem(0) };
  }
});
