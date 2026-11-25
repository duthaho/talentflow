import { createBffProxy } from "@/lib/api/bff-proxy";
import { getSession } from "@/lib/auth/session";
import { config } from "@/lib/config";

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: Request, context: Context) {
  const forward = createBffProxy({
    apiBaseUrl: config().apiBaseUrl,
    appOrigin: new URL(config().appBaseUrl).origin,
    accessToken: async () => (await getSession())?.accessToken,
  });
  return forward(request, (await context.params).path);
}

export { handle as GET, handle as POST, handle as PATCH, handle as PUT, handle as DELETE };
