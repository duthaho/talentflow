"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { browserApi, settle, type ApiClient, type ApiResult } from "@/lib/api/client";
import { describeProblem } from "@/lib/api/problem";
import type { components } from "@/lib/api/schema";

type Requisition = components["schemas"]["RequisitionResponse"];

export function RequisitionsWorkspace({ canPublish, api: injectedApi }: { canPublish: boolean; api?: ApiClient }) {
  const api = useMemo(() => injectedApi ?? browserApi(), [injectedApi]);
  const [jobs, setJobs] = useState<Requisition[]>([]);
  const [slug, setSlug] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchPage = useCallback((next: string | null) =>
    settle(api.GET("/v1/requisitions", { params: { query: { limit: 25, cursor: next ?? undefined } } })), [api]);

  const acceptPage = useCallback((result: ApiResult<components["schemas"]["RequisitionListResponse"]>, next: string | null) => {
    if (result.ok) {
      setError(null);
      setJobs((current) => next ? [...current, ...result.data.items] : result.data.items);
      setSlug(result.data.tenant_slug);
      setCursor(result.data.next_cursor);
    } else setError(describeProblem(result.problem).description);
    setLoading(false);
  }, []);

  useEffect(() => {
    let active = true;
    void fetchPage(null).then((result) => { if (active) acceptPage(result, null); });
    return () => { active = false; };
  }, [fetchPage, acceptPage]);

  async function load(next: string | null) {
    setLoading(true);
    acceptPage(await fetchPage(next), next);
  }

  async function toggle(job: Requisition) {
    setSaving(job.id);
    setError(null);
    const result = await settle(api.PATCH("/v1/requisitions/{id}/publication", {
      params: { path: { id: job.id } }, body: { published: !job.published },
    }));
    if (result.ok) setJobs((current) => current.map((item) => item.id === job.id ? result.data : item));
    else setError(describeProblem(result.problem).description);
    setSaving(null);
  }

  return <section className="space-y-6" aria-label="Requisition publication" aria-busy={loading}>
    {slug && <div className="rounded-lg border p-4">
      <p className="text-sm font-medium">Public careers URL</p>
      <a className="text-sm underline" href={`/careers/${encodeURIComponent(slug)}`}>{`/careers/${slug}`}</a>
      <p className="mt-1 text-sm text-muted-foreground">The public careers page will be available in the next release.</p>
    </div>}
    {error && <div role="alert" className="space-y-2"><p>{error}</p><Button variant="outline" onClick={() => void load(null)}>Reload requisitions</Button></div>}
    {loading && jobs.length === 0 && <p role="status">Loading requisitions…</p>}
    {!loading && !error && jobs.length === 0 && <p>No requisitions yet.</p>}
    <ul className="divide-y rounded-lg border">
      {jobs.map((job) => <li key={job.id} className="flex items-center justify-between gap-4 p-4">
        <div><p className="font-medium">{job.title}</p><p className="text-sm text-muted-foreground">{job.department}</p><p className="text-sm">{job.published ? "Published" : "Unpublished"}</p></div>
        {canPublish && <button type="button" role="switch" aria-checked={job.published} aria-label={`Publish ${job.title}`} disabled={saving !== null} onClick={() => void toggle(job)} className="rounded-md border px-3 py-2 text-sm disabled:opacity-50">
          {saving === job.id ? "Saving…" : job.published ? "Unpublish" : "Publish"}
        </button>}
      </li>)}
    </ul>
    {cursor && <Button variant="outline" disabled={loading} onClick={() => void load(cursor)}>Load more</Button>}
  </section>;
}
