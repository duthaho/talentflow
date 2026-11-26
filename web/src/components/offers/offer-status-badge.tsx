import { Badge } from "@/components/ui/badge";
import { statusLabel } from "@/lib/offers/format";

const VARIANTS = { pending_approval: "secondary", approved: "default", rejected: "destructive" } as const;

export function OfferStatusBadge({ status }: { status: string }) {
  return <Badge variant={VARIANTS[status as keyof typeof VARIANTS] ?? "outline"}>{statusLabel(status)}</Badge>;
}
