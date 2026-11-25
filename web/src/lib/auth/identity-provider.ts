import * as oidc from "openid-client";

export type TokenSet = {
  accessToken: string;
  expiresInSeconds: number;
  refreshToken?: string;
  refreshExpiresInSeconds?: number;
  idToken?: string;
  claims?: Record<string, unknown>;
};

export type AuthorizationChecks = {
  codeVerifier: string;
  state: string;
  nonce: string;
};

export interface IdentityProvider {
  authorizationUrl(params: {
    redirectUri: string;
    codeChallenge: string;
    state: string;
    nonce: string;
  }): URL;
  exchangeCode(callbackUrl: URL, checks: AuthorizationChecks): Promise<TokenSet>;
  refresh(refreshToken: string): Promise<TokenSet>;
  revoke(refreshToken: string): Promise<void>;
  endSessionUrl(params: { idToken?: string; postLogoutRedirectUri: string }): URL;
}

export type KeycloakEndpoints = {
  publicIssuer: string;
  internalIssuer: string;
  clientId: string;
};

// The browser reaches Keycloak on the public issuer while the web server, inside the compose
// network, reaches it on the internal hostname. Discovery would hand back public URLs only, so
// the metadata is assembled explicitly: browser-facing endpoints public, back-channel internal.
export function keycloakMetadata({ publicIssuer, internalIssuer }: KeycloakEndpoints): oidc.ServerMetadata {
  const browser = `${publicIssuer}/protocol/openid-connect`;
  const backChannel = `${internalIssuer}/protocol/openid-connect`;
  return {
    issuer: publicIssuer,
    authorization_endpoint: `${browser}/auth`,
    end_session_endpoint: `${browser}/logout`,
    token_endpoint: `${backChannel}/token`,
    revocation_endpoint: `${backChannel}/revoke`,
    userinfo_endpoint: `${backChannel}/userinfo`,
    jwks_uri: `${backChannel}/certs`,
    code_challenge_methods_supported: ["S256"],
  };
}

function toTokenSet(response: oidc.TokenEndpointResponse & oidc.TokenEndpointResponseHelpers): TokenSet {
  const refreshExpiresIn = (response as { refresh_expires_in?: unknown }).refresh_expires_in;
  return {
    accessToken: response.access_token,
    expiresInSeconds: response.expiresIn() ?? 60,
    refreshToken: response.refresh_token,
    refreshExpiresInSeconds: typeof refreshExpiresIn === "number" ? refreshExpiresIn : undefined,
    idToken: response.id_token,
    claims: response.claims() as Record<string, unknown> | undefined,
  };
}

export class KeycloakIdentityProvider implements IdentityProvider {
  private readonly configuration: oidc.Configuration;

  constructor(endpoints: KeycloakEndpoints) {
    this.configuration = new oidc.Configuration(
      keycloakMetadata(endpoints),
      endpoints.clientId,
      undefined,
      oidc.None(),
    );
    if (endpoints.internalIssuer.startsWith("http://") || endpoints.publicIssuer.startsWith("http://")) {
      oidc.allowInsecureRequests(this.configuration);
    }
  }

  authorizationUrl({ redirectUri, codeChallenge, state, nonce }: Parameters<IdentityProvider["authorizationUrl"]>[0]) {
    return oidc.buildAuthorizationUrl(this.configuration, {
      redirect_uri: redirectUri,
      scope: "openid profile email",
      response_type: "code",
      code_challenge: codeChallenge,
      code_challenge_method: "S256",
      state,
      nonce,
    });
  }

  async exchangeCode(callbackUrl: URL, checks: AuthorizationChecks) {
    const response = await oidc.authorizationCodeGrant(this.configuration, callbackUrl, {
      pkceCodeVerifier: checks.codeVerifier,
      expectedState: checks.state,
      expectedNonce: checks.nonce,
      idTokenExpected: true,
    });
    return toTokenSet(response);
  }

  async refresh(refreshToken: string) {
    return toTokenSet(await oidc.refreshTokenGrant(this.configuration, refreshToken));
  }

  async revoke(refreshToken: string) {
    await oidc.tokenRevocation(this.configuration, refreshToken, { token_type_hint: "refresh_token" });
  }

  endSessionUrl({ idToken, postLogoutRedirectUri }: { idToken?: string; postLogoutRedirectUri: string }) {
    const params: Record<string, string> = { post_logout_redirect_uri: postLogoutRedirectUri };
    if (idToken) params.id_token_hint = idToken;
    else params.client_id = this.configuration.clientMetadata().client_id;
    return oidc.buildEndSessionUrl(this.configuration, params);
  }
}
