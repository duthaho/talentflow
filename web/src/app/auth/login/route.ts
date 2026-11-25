import { NextResponse, type NextRequest } from "next/server";

import { LOGIN_TTL_SECONDS } from "@/lib/auth/auth-service";
import { authService, cookieOptions, LOGIN_COOKIE } from "@/lib/auth/session";

export async function GET(request: NextRequest) {
  const { loginId, authorizationUrl } = await authService().beginLogin(
    request.nextUrl.searchParams.get("returnTo"),
  );
  const response = NextResponse.redirect(authorizationUrl);
  response.cookies.set(LOGIN_COOKIE, loginId, cookieOptions(LOGIN_TTL_SECONDS));
  return response;
}
