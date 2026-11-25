import { describe, expect, it } from "vitest";

import { ResponseBodyError } from "openid-client";

import {
  classifyRefreshError,
  IdentityProviderUnavailableError,
  KeycloakIdentityProvider,
  keycloakMetadata,
  RefreshRejectedError,
} from "./identity-provider";

const endpoints = {
  publicIssuer: "http://localhost:8081/realms/talentflow",
  internalIssuer: "http://keycloak:8080/realms/talentflow",
  clientId: "talentflow-api",
};

describe("Keycloak endpoints", () => {
  it("sends the browser to the public host and keeps back-channel calls internal", () => {
    const metadata = keycloakMetadata(endpoints);
    expect(metadata.issuer).toBe(endpoints.publicIssuer);
    expect(metadata.authorization_endpoint).toMatch(/^http:\/\/localhost:8081\//);
    expect(metadata.end_session_endpoint).toMatch(/^http:\/\/localhost:8081\//);
    expect(metadata.token_endpoint).toMatch(/^http:\/\/keycloak:8080\//);
    expect(metadata.jwks_uri).toMatch(/^http:\/\/keycloak:8080\//);
  });

  it("builds an authorization code request with PKCE S256", () => {
    const url = new KeycloakIdentityProvider(endpoints).authorizationUrl({
      redirectUri: "http://localhost:3000/auth/callback",
      codeChallenge: "challenge",
      state: "state",
      nonce: "nonce",
    });
    expect(url.origin).toBe("http://localhost:8081");
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      client_id: "talentflow-api",
      response_type: "code",
      code_challenge: "challenge",
      code_challenge_method: "S256",
      state: "state",
      nonce: "nonce",
      scope: "openid profile email",
    });
  });

  it("builds the end-session URL with the id token hint, or the client id without one", () => {
    const provider = new KeycloakIdentityProvider(endpoints);
    const withHint = provider.endSessionUrl({ idToken: "id", postLogoutRedirectUri: "http://localhost:3000/signed-out" });
    expect(withHint.searchParams.get("id_token_hint")).toBe("id");
    const withoutHint = provider.endSessionUrl({ postLogoutRedirectUri: "http://localhost:3000/signed-out" });
    expect(withoutHint.searchParams.get("client_id")).toBe("talentflow-api");
  });
});

describe("classifyRefreshError", () => {
  const bodyError = (error: string, status: number) =>
    new ResponseBodyError("token error", { cause: { error }, response: new Response(null, { status }) });

  it("treats only invalid_grant as the end of the session", () => {
    expect(classifyRefreshError(bodyError("invalid_grant", 400))).toBeInstanceOf(RefreshRejectedError);
  });

  it("treats other token errors and network failures as a transient outage", () => {
    expect(classifyRefreshError(bodyError("temporarily_unavailable", 503))).toBeInstanceOf(IdentityProviderUnavailableError);
    expect(classifyRefreshError(new TypeError("fetch failed"))).toBeInstanceOf(IdentityProviderUnavailableError);
  });
});
