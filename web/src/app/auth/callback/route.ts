import { NextResponse, type NextRequest } from "next/server";

import { LoginError } from "@/lib/auth/auth-service";
import { authService, cookieOptions, LOGIN_COOKIE, SESSION_COOKIE } from "@/lib/auth/session";
import { config } from "@/lib/config";

export async function GET(request: NextRequest) {
  const loginId = request.cookies.get(LOGIN_COOKIE)?.value;
  try {
    const { sessionId, returnTo, ttlSeconds } = await authService().completeLogin(
      loginId,
      request.nextUrl.search,
    );
    const response = NextResponse.redirect(new URL(returnTo, config().appBaseUrl));
    response.cookies.delete(LOGIN_COOKIE);
    response.cookies.set(SESSION_COOKIE, sessionId, cookieOptions(ttlSeconds));
    return response;
  } catch (error) {
    const reason = error instanceof LoginError ? error.message : "The sign-in could not be completed.";
    if (!(error instanceof LoginError)) console.error("OIDC callback failed", error);
    const target = new URL("/signed-out", config().appBaseUrl);
    target.searchParams.set("error", reason);
    const response = NextResponse.redirect(target);
    response.cookies.delete(LOGIN_COOKIE);
    return response;
  }
}
