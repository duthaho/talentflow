import type { ChartDatum } from "@/lib/reports/pipeline-report";

// Rendered as a table so screen readers get the exact numbers; the bars are decoration on top of it.
export function BarChart({ caption, data, unit }: { caption: string; data: ChartDatum[]; unit: string }) {
  const max = Math.max(0, ...data.map((datum) => datum.value));
  return (
    <table className="w-full border-separate border-spacing-y-2 text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead className="sr-only">
        <tr>
          <th scope="col">Category</th>
          <th scope="col">{unit}</th>
        </tr>
      </thead>
      <tbody>
        {data.map((datum) => (
          <tr key={datum.key} data-key={datum.key}>
            <th scope="row" className="w-36 pr-3 text-left font-normal text-muted-foreground sm:w-40">
              {datum.label}
            </th>
            <td>
              <div className="flex items-center gap-2">
                <div className="h-4 flex-1 overflow-hidden rounded-sm bg-muted" aria-hidden>
                  <div
                    data-testid="bar"
                    className="h-full rounded-sm bg-primary"
                    style={{ width: max === 0 ? "0%" : `${(datum.value / max) * 100}%` }}
                  />
                </div>
                <span className="w-10 text-right font-medium tabular-nums">{datum.value}</span>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
