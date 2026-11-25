import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  const forwarded = new Headers(request.headers);
  forwarded.set("x-return-to", `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.next({ request: { headers: forwarded } });
}

export const config = {
  matcher: ["/((?!api/|auth/|_next/|favicon.ico).*)"],
};
