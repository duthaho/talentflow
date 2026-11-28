import { ProblemView } from "@/components/problem/problem-view";
import { forbiddenProblem } from "@/components/app-shell/require-permission";
import { navItem } from "@/lib/nav";

export default function WebhooksForbidden() {
  return <ProblemView problem={forbiddenProblem(navItem("/settings/webhooks"))} />;
}
