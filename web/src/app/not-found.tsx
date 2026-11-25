import { ProblemView } from "@/components/problem/problem-view";
import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";

export default function NotFound() {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <ProblemView
        problem={{ type: `${PROBLEM_TYPE_BASE}not-found`, title: "Not Found", status: 404, detail: "This page does not exist." }}
      />
    </main>
  );
}
