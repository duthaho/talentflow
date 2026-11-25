export const SESSION_COOKIE = "tf_session";
export const LOGIN_COOKIE = "tf_login";

function baseOptions(secure: boolean) {
  return { httpOnly: true, sameSite: "lax" as const, secure, path: "/" };
}

// No maxAge: Redis owns the session lifetime and extends it on every refresh, so a fixed browser
// expiry would log active users out when the first refresh window ends.
export function sessionCookieOptions(secure: boolean) {
  return baseOptions(secure);
}

export function loginCookieOptions(secure: boolean, maxAgeSeconds: number) {
  return { ...baseOptions(secure), maxAge: maxAgeSeconds };
}
