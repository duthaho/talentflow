import { NextResponse, type NextRequest } from "next/server";

import { LOGIN_TTL_SECONDS } from "@/lib/auth/auth-service";
import { LOGIN_COOKIE, loginCookieOptions } from "@/lib/auth/cookies";
import { authService } from "@/lib/auth/session";
import { config } from "@/lib/config";

export async function GET(request: NextRequest) {
  const { loginId, authorizationUrl } = await authService().beginLogin(
    request.nextUrl.searchParams.get("returnTo"),
  );
  const response = NextResponse.redirect(authorizationUrl);
  response.cookies.set(LOGIN_COOKIE, loginId, loginCookieOptions(config().secureCookies, LOGIN_TTL_SECONDS));
  return response;
}
