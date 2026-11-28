import type { Actor, FeatureName, Permission } from "@/lib/actor/actor";

export type NavItem = {
  href: string;
  label: string;
  description: string;
  anyOf: Permission[];
  feature?: FeatureName;
  icon: "home" | "users" | "calendar" | "file-signature" | "chart" | "scroll" | "archive" | "webhook";
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Overview", description: "Your workspace at a glance.", anyOf: [], icon: "home" },
  { href: "/candidates", label: "Candidates", description: "Candidate cases and the hiring pipeline.", anyOf: ["tenant:read"], icon: "users" },
  { href: "/interviews", label: "Interviews", description: "Schedule interviews and submit feedback.", anyOf: ["interview:manage", "feedback:submit"], icon: "calendar" },
  { href: "/offers", label: "Offers", description: "Offers and staged approvals.", anyOf: ["tenant:read"], icon: "file-signature" },
  { href: "/reports", label: "Reports", description: "Pipeline reporting.", anyOf: ["report:read"], icon: "chart" },
  { href: "/audit", label: "Audit log", description: "Who did what, and when.", anyOf: ["audit:read"], icon: "scroll" },
  { href: "/settings/requisitions", label: "Requisitions", description: "Publish jobs to your careers page.", anyOf: ["tenant:read"], icon: "file-signature" },
  { href: "/settings/retention", label: "Retention", description: "Retention policy and legal holds.", anyOf: ["retention:manage"], icon: "archive" },
  { href: "/settings/webhooks", label: "Webhooks", description: "Send hiring events to your own systems.", anyOf: ["webhook:manage"], feature: "webhooks", icon: "webhook" },
];

export function isAllowed(item: Pick<NavItem, "anyOf">, permissions: readonly Permission[]): boolean {
  return item.anyOf.length === 0 || item.anyOf.some((permission) => permissions.includes(permission));
}

// The page behind a feature-gated item stays reachable by URL (ADR-010 §4); only the link is hidden.
export function visibleNav(actor: Pick<Actor, "permissions" | "features">): NavItem[] {
  return NAV_ITEMS.filter((item) => isAllowed(item, actor.permissions) && (!item.feature || actor.features[item.feature].enabled));
}

export function navItem(href: string): NavItem {
  const item = NAV_ITEMS.find((candidate) => candidate.href === href);
  if (!item) throw new Error(`Unknown nav item ${href}`);
  return item;
}

export function isActive(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
