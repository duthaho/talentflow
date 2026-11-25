import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/auth/cookies";
import { authService } from "@/lib/auth/session";
import { config } from "@/lib/config";
import { isSameOrigin } from "@/lib/http/same-origin";

export async function POST(request: NextRequest) {
  if (!isSameOrigin(request, new URL(config().appBaseUrl).origin)) {
    return new NextResponse("Cross-origin sign-out is not allowed.", { status: 403 });
  }
  const endSessionUrl = await authService().logout(
    request.cookies.get(SESSION_COOKIE)?.value,
    `${config().appBaseUrl}/signed-out`,
  );
  const response = NextResponse.redirect(endSessionUrl, 303);
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
