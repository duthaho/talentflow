// SameSite=Lax still sends cookies from other ports on the same host, which count as same-site.
export function isSameOrigin(request: Request, appOrigin: string): boolean {
  const origin = request.headers.get("origin");
  if (origin) return origin === appOrigin;
  return request.headers.get("sec-fetch-site") === "same-origin";
}
