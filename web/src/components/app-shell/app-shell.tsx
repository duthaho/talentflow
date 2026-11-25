import { LogOut } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ROLE_LABELS, type Actor } from "@/lib/actor/actor";
import { visibleNav } from "@/lib/nav";

import { MobileNav } from "./mobile-nav";
import { NavLinks } from "./nav-links";

export function AppShell({ actor, children }: { actor: Actor; children: ReactNode }) {
  const items = visibleNav(actor.permissions);
  return (
    <div className="flex min-h-svh flex-1 flex-col md:flex-row">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 focus:not-sr-only focus:absolute focus:left-2 focus:top-2"
      >
        Skip to content
      </a>
      <aside className="hidden w-64 shrink-0 flex-col border-r bg-sidebar md:flex">
        <div className="px-6 py-5">
          <p className="text-lg font-semibold tracking-tight">TalentFlow</p>
          <p className="truncate text-sm text-muted-foreground" title={actor.tenantId}>
            {actor.tenantName}
          </p>
        </div>
        <nav aria-label="Main" className="px-3">
          <NavLinks items={items} />
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b px-4 py-3 md:px-8">
          <MobileNav items={items} tenantName={actor.tenantName} />
          <p className="font-semibold md:hidden">TalentFlow</p>
          <div className="ml-auto flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium leading-tight">{actor.displayName}</p>
              <p className="text-xs text-muted-foreground">{actor.email}</p>
            </div>
            {actor.role && <Badge variant="secondary">{ROLE_LABELS[actor.role]}</Badge>}
            <form action="/auth/logout" method="post">
              <Button type="submit" variant="outline" size="sm">
                <LogOut aria-hidden />
                Sign out
              </Button>
            </form>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="flex-1 px-4 py-6 outline-none md:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
