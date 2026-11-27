"use client";

import { Archive, CalendarDays, ChartColumn, FileSignature, House, ScrollText, Users, Webhook } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { isActive, type NavItem } from "@/lib/nav";

const ICONS: Record<NavItem["icon"], typeof House> = {
  home: House,
  users: Users,
  calendar: CalendarDays,
  "file-signature": FileSignature,
  chart: ChartColumn,
  scroll: ScrollText,
  archive: Archive,
  webhook: Webhook,
};

export function NavLinks({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <ul className="flex flex-col gap-1">
      {items.map((item) => {
        const Icon = ICONS[item.icon];
        const active = isActive(item.href, pathname);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
                active && "bg-muted text-foreground",
              )}
            >
              <Icon aria-hidden className="size-4" />
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
