import { Construction } from "lucide-react";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { navItem } from "@/lib/nav";

import { PageHeader } from "./page-header";
import { RequirePermission } from "./require-permission";

export function PlannedScreen({ href, plannedIn }: { href: string; plannedIn: string }) {
  const item = navItem(href);
  return (
    <RequirePermission item={item}>
      <PageHeader title={item.label} description={item.description} />
      <Card className="max-w-xl border-dashed">
        <CardHeader>
          <Construction aria-hidden className="mb-2 size-6 text-muted-foreground" />
          <CardTitle role="heading" aria-level={2}>
            Coming in {plannedIn}
          </CardTitle>
          <CardDescription>
            This screen is part of the web app roadmap. Your role already has access, so it will appear here as soon as
            it ships.
          </CardDescription>
        </CardHeader>
      </Card>
    </RequirePermission>
  );
}
