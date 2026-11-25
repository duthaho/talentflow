import { randomBytes } from "node:crypto";
import { calculatePKCECodeChallenge, randomNonce, randomPKCECodeVerifier, randomState } from "openid-client";

import type { IdentityProvider, TokenSet } from "./identity-provider";
import type { SessionStore, StoredSession } from "./session-store";

export const LOGIN_TTL_SECONDS = 600;
export const DEFAULT_SESSION_TTL_SECONDS = 1800;
export const REFRESH_LEEWAY_MS = 30_000;

export class LoginError extends Error {}

export function safeReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return "/";
  }
  return value;
}

function newId(): string {
  return randomBytes(32).toString("base64url");
}

function stringClaim(claims: Record<string, unknown> | undefined, name: string): string {
  const value = claims?.[name];
  return typeof value === "string" ? value : "";
}

export type AuthServiceDeps = {
  provider: IdentityProvider;
  store: SessionStore;
  appBaseUrl: string;
  now?: () => number;
};

export class AuthService {
  private readonly now: () => number;

  constructor(private readonly deps: AuthServiceDeps) {
    this.now = deps.now ?? Date.now;
  }

  get redirectUri(): string {
    return `${this.deps.appBaseUrl}/auth/callback`;
  }

  async beginLogin(returnTo: string | null): Promise<{ loginId: string; authorizationUrl: URL }> {
    const codeVerifier = randomPKCECodeVerifier();
    const state = randomState();
    const nonce = randomNonce();
    const loginId = newId();
    await this.deps.store.savePendingLogin(
      loginId,
      { codeVerifier, state, nonce, returnTo: safeReturnTo(returnTo) },
      LOGIN_TTL_SECONDS,
    );
    const authorizationUrl = this.deps.provider.authorizationUrl({
      redirectUri: this.redirectUri,
      codeChallenge: await calculatePKCECodeChallenge(codeVerifier),
      state,
      nonce,
    });
    return { loginId, authorizationUrl };
  }

  async completeLogin(
    loginId: string | undefined,
    callbackSearch: string,
  ): Promise<{ sessionId: string; returnTo: string; ttlSeconds: number }> {
    const pending = loginId ? await this.deps.store.takePendingLogin(loginId) : null;
    if (!pending) {
      throw new LoginError("The sign-in attempt expired or was already used.");
    }
    const callbackUrl = new URL(`${this.redirectUri}${callbackSearch}`);
    const providerError = callbackUrl.searchParams.get("error");
    if (providerError) {
      throw new LoginError(`Keycloak rejected the sign-in: ${providerError}`);
    }
    const tokens = await this.deps.provider.exchangeCode(callbackUrl, pending);
    const tenantId = stringClaim(tokens.claims, "tenant_id");
    const subject = stringClaim(tokens.claims, "sub");
    if (!tenantId || !subject) {
      throw new LoginError("The identity token has no tenant or subject claim.");
    }
    const sessionId = newId();
    const ttlSeconds = this.sessionTtl(tokens);
    await this.deps.store.saveSession(
      sessionId,
      {
        subject,
        tenantId,
        email: stringClaim(tokens.claims, "email"),
        name: stringClaim(tokens.claims, "name") || stringClaim(tokens.claims, "preferred_username"),
        ...this.tokenFields(tokens),
      },
      ttlSeconds,
    );
    return { sessionId, returnTo: pending.returnTo, ttlSeconds };
  }

  async currentSession(sessionId: string | undefined): Promise<StoredSession | null> {
    if (!sessionId) return null;
    const session = await this.deps.store.getSession(sessionId);
    if (!session) return null;
    if (session.accessTokenExpiresAt - REFRESH_LEEWAY_MS > this.now()) return session;
    if (!session.refreshToken) {
      await this.deps.store.deleteSession(sessionId);
      return null;
    }
    try {
      const tokens = await this.deps.provider.refresh(session.refreshToken);
      const refreshed: StoredSession = {
        ...session,
        ...this.tokenFields(tokens),
        refreshToken: tokens.refreshToken ?? session.refreshToken,
        idToken: tokens.idToken ?? session.idToken,
      };
      await this.deps.store.saveSession(sessionId, refreshed, this.sessionTtl(tokens));
      return refreshed;
    } catch {
      await this.deps.store.deleteSession(sessionId);
      return null;
    }
  }

  async logout(sessionId: string | undefined, postLogoutRedirectUri: string): Promise<URL> {
    const session = sessionId ? await this.deps.store.getSession(sessionId) : null;
    if (sessionId) await this.deps.store.deleteSession(sessionId);
    if (session?.refreshToken) {
      await this.deps.provider.revoke(session.refreshToken).catch(() => undefined);
    }
    return this.deps.provider.endSessionUrl({ idToken: session?.idToken, postLogoutRedirectUri });
  }

  private tokenFields(tokens: TokenSet) {
    return {
      accessToken: tokens.accessToken,
      accessTokenExpiresAt: this.now() + tokens.expiresInSeconds * 1000,
      refreshToken: tokens.refreshToken,
      idToken: tokens.idToken,
    };
  }

  private sessionTtl(tokens: TokenSet): number {
    return tokens.refreshExpiresInSeconds || DEFAULT_SESSION_TTL_SECONDS;
  }
}
