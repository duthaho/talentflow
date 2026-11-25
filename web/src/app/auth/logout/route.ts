import { NextResponse, type NextRequest } from "next/server";

import { authService, SESSION_COOKIE } from "@/lib/auth/session";
import { config } from "@/lib/config";

export async function POST(request: NextRequest) {
  const endSessionUrl = await authService().logout(
    request.cookies.get(SESSION_COOKIE)?.value,
    `${config().appBaseUrl}/signed-out`,
  );
  const response = NextResponse.redirect(endSessionUrl, 303);
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
