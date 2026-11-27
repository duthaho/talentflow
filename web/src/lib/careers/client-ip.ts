import "server-only";
import { isIP } from "node:net";

// ingress.cjs overwrites this header at the socket boundary, including for SSR.
// With N trusted proxies, select N positions to the left of the socket peer.
export function clientIp(
  headers: Pick<Headers, "get">,
  trustedHops = Number(process.env.CAREERS_TRUSTED_PROXY_HOPS ?? "0"),
): string {
  if (!Number.isSafeInteger(trustedHops) || trustedHops < 0)
    throw new Error("Invalid proxy hop count");
  const chain = (headers.get("x-talentflow-ip-chain") ?? "")
    .split(",")
    .map((value) => value.trim());
  const ip = chain[chain.length - 1 - trustedHops];
  if (!ip || !isIP(ip)) throw new Error("Client address unavailable");
  return ip;
}
