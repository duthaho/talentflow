import "server-only";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { config } from "@/lib/config";

import { AuthService } from "./auth-service";
import { KeycloakIdentityProvider } from "./identity-provider";
import { RedisKeyValueStore, SessionStore, type StoredSession } from "./session-store";

export const SESSION_COOKIE = "tf_session";
export const LOGIN_COOKIE = "tf_login";

let service: AuthService | undefined;

export function authService(): AuthService {
  if (!service) {
    const settings = config();
    service = new AuthService({
      provider: new KeycloakIdentityProvider({
        publicIssuer: settings.oidcIssuer,
        internalIssuer: settings.oidcInternalIssuer,
        clientId: settings.oidcClientId,
      }),
      store: new SessionStore(new RedisKeyValueStore(settings.redisUrl)),
      appBaseUrl: settings.appBaseUrl,
    });
  }
  return service;
}

export function cookieOptions(maxAgeSeconds: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: config().secureCookies,
    path: "/",
    maxAge: maxAgeSeconds,
  };
}

export const getSession = cache(async (): Promise<StoredSession | null> => {
  const sessionId = (await cookies()).get(SESSION_COOKIE)?.value;
  return authService().currentSession(sessionId);
});

export async function requireSession(): Promise<StoredSession> {
  const session = await getSession();
  if (!session) {
    const returnTo = (await headers()).get("x-return-to") ?? "/";
    redirect(`/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
  }
  return session;
}
