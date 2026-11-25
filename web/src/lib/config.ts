import "server-only";

export type WebConfig = {
  appBaseUrl: string;
  apiBaseUrl: string;
  oidcIssuer: string;
  oidcInternalIssuer: string;
  oidcClientId: string;
  redisUrl: string;
  actorSource: "api" | "mock";
  secureCookies: boolean;
};

function required(env: NodeJS.ProcessEnv, name: string, fallback?: string): string {
  const value = env[name] ?? fallback;
  if (!value) {
    throw new Error(`Missing required environment variable ${name}`);
  }
  return value.replace(/\/+$/, "");
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): WebConfig {
  const appBaseUrl = required(env, "APP_BASE_URL", "http://localhost:3000");
  const oidcIssuer = required(env, "OIDC_ISSUER", "http://localhost:8081/realms/talentflow");
  const actorSource = env.ACTOR_SOURCE ?? "api";
  if (actorSource !== "api" && actorSource !== "mock") {
    throw new Error("ACTOR_SOURCE must be 'api' or 'mock'");
  }
  return {
    appBaseUrl,
    apiBaseUrl: required(env, "API_BASE_URL", "http://localhost:8000"),
    oidcIssuer,
    oidcInternalIssuer: required(env, "OIDC_INTERNAL_ISSUER", oidcIssuer),
    oidcClientId: required(env, "OIDC_CLIENT_ID", "talentflow-api"),
    redisUrl: required(env, "REDIS_URL", "redis://localhost:6379/1"),
    actorSource,
    secureCookies: appBaseUrl.startsWith("https://"),
  };
}

let cached: WebConfig | undefined;

export function config(): WebConfig {
  cached ??= loadConfig();
  return cached;
}
