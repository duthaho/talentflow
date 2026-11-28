import { settle, type ApiClient } from "@/lib/api/client";

import { isTerminal, type WebhookDelivery } from "./format";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function followDelivery(
  api: ApiClient,
  delivery: WebhookDelivery,
  { intervalMs, timeoutMs, onUpdate, isActive }: { intervalMs: number; timeoutMs: number; onUpdate: (delivery: WebhookDelivery) => void; isActive: () => boolean },
): Promise<WebhookDelivery> {
  let latest = delivery;
  const deadline = Date.now() + timeoutMs;
  while (!isTerminal(latest.status) && Date.now() < deadline) {
    await wait(intervalMs);
    if (!isActive()) return latest;
    const polled = await settle(api.GET("/v1/webhook-deliveries/{delivery_id}", { params: { path: { delivery_id: latest.id } } }));
    if (!isActive() || !polled.ok) return latest;
    latest = polled.data;
    onUpdate(latest);
  }
  return latest;
}
