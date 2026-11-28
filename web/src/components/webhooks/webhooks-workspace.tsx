"use client";

import { CirclePause, Info, KeyRound, ListOrdered, Pencil, Plus, Power, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { FormProblem } from "@/components/pipeline/form-fields";
import { toastProblem } from "@/components/problem/toast-problem";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi, settle, type ApiClient } from "@/lib/api/client";
import { ifMatch } from "@/lib/api/precondition";
import type { Features } from "@/lib/actor/actor";
import { describeProblem, isFeatureDisabled, type ProblemDetails } from "@/lib/api/problem";
import { formatTimestamp } from "@/lib/candidates/detail";
import { useResource } from "@/lib/candidates/use-resource";
import { disabledReasonLabel, hostOf, isStale, type WebhookEndpoint } from "@/lib/webhooks/format";

import { DeliveryLog } from "./delivery-log";
import { EndpointDialog, type EndpointDialogTarget } from "./endpoint-dialog";
import { RotateSecretDialog, SecretRevealDialog, type RevealedSecret } from "./secret-dialogs";

// ADR-008 caps a tenant at 10 endpoints, so one page at the API maximum always holds them all.
const ENDPOINT_PAGE_LIMIT = 100;

type EndpointsState = { status: "loading" } | { status: "ready"; items: WebhookEndpoint[] } | { status: "error"; problem: ProblemDetails };

export function WebhooksWorkspace({
  feature,
  api: injectedApi,
  pollIntervalMs,
  pollTimeoutMs,
}: {
  feature: Features["webhooks"];
  api?: ApiClient;
  pollIntervalMs?: number;
  pollTimeoutMs?: number;
}) {
  const api = useMemo(() => injectedApi ?? browserApi(), [injectedApi]);
  const [endpoints, setEndpoints] = useState<EndpointsState>({ status: "loading" });
  const [reloads, setReloads] = useState(0);
  const generation = useRef(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<EndpointDialogTarget | null>(null);
  const [rotating, setRotating] = useState<WebhookEndpoint | null>(null);
  const [deleting, setDeleting] = useState<WebhookEndpoint | null>(null);
  const [revealed, setRevealed] = useState<RevealedSecret | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const router = useRouter();
  const [disabledByApi, setDisabledByApi] = useState(false);
  const [renderedFeature, setRenderedFeature] = useState(feature);
  // `feature` comes from the server page, so a new object means a fresh /v1/me render (ADR-010 §4).
  // That render is authoritative even when its value matches the one before the refused mutation.
  if (renderedFeature !== feature) {
    setRenderedFeature(feature);
    setDisabledByApi(false);
  }
  const enabled = feature.enabled && !disabledByApi;

  const eventTypes = useResource(useCallback(() => settle(api.GET("/v1/webhook-event-types")), [api]));

  useEffect(() => {
    const run = ++generation.current;
    void settle(api.GET("/v1/webhook-endpoints", { params: { query: { limit: ENDPOINT_PAGE_LIMIT } } })).then((result) => {
      if (run !== generation.current) return;
      setEndpoints(result.ok ? { status: "ready", items: result.data.items } : { status: "error", problem: result.problem });
    });
  }, [api, reloads]);

  const reload = useCallback(() => {
    setEndpoints({ status: "loading" });
    setReloads((count) => count + 1);
  }, []);

  function upsert(endpoint: WebhookEndpoint) {
    setEndpoints((current) => {
      if (current.status !== "ready") return current;
      const exists = current.items.some((item) => item.id === endpoint.id);
      return { status: "ready", items: exists ? current.items.map((item) => (item.id === endpoint.id ? endpoint : item)) : [endpoint, ...current.items] };
    });
  }

  // A redelivery is an endpoint write (ADR-008), so the API bumps its version; refetch to keep If-Match current.
  async function refreshEndpoint(id: string) {
    const result = await settle(api.GET("/v1/webhook-endpoints/{endpoint_id}", { params: { path: { endpoint_id: id } } }));
    if (result.ok) upsert(result.data);
  }

  function onStale(problem: ProblemDetails) {
    setDialog(null);
    setRotating(null);
    setDeleting(null);
    toastProblem(problem);
    reload();
  }

  // ADR-010 §4: the gate closed mid-session. Switch to the read-only view now, then re-render the
  // server tree so the shell and this page pick up the fresh /v1/me state.
  function onFeatureDisabled() {
    setDialog(null);
    setDisabledByApi(true);
    router.refresh();
  }

  async function toggle(endpoint: WebhookEndpoint) {
    setToggling(endpoint.id);
    const enabled = endpoint.status !== "enabled";
    const result = await settle(
      api.PATCH("/v1/webhook-endpoints/{endpoint_id}", {
        params: { path: { endpoint_id: endpoint.id }, header: { "If-Match": ifMatch(endpoint.version) } },
        body: { enabled },
      }),
    );
    setToggling(null);
    if (result.ok) {
      upsert(result.data);
      toast.success(enabled ? `Enabled ${hostOf(endpoint.url)}.` : `Disabled ${hostOf(endpoint.url)}. Pending deliveries were cancelled.`);
    } else if (isStale(result.problem)) onStale(result.problem);
    else if (isFeatureDisabled(result.problem)) onFeatureDisabled();
    else toastProblem(result.problem);
  }

  const selected = endpoints.status === "ready" ? (endpoints.items.find((item) => item.id === selectedId) ?? null) : null;
  const typesReady = eventTypes.state.status === "ready";

  return (
    <div className="space-y-8">
      {!enabled && (
        <Alert role="status">
          <Info aria-hidden />
          <AlertTitle>Webhooks are turned off</AlertTitle>
          <AlertDescription>
            Webhooks are turned off for your organization. You can still view, disable, rotate or delete existing endpoints. Events for enabled endpoints are kept and
            sent if webhooks are turned back on.
          </AlertDescription>
        </Alert>
      )}
      {enabled && feature.deliveryPaused && (
        <Alert role="status" className="border-amber-500/50 bg-amber-50 text-amber-950 dark:bg-amber-950/30 dark:text-amber-100">
          <CirclePause aria-hidden />
          <AlertTitle>Delivery is paused</AlertTitle>
          <AlertDescription className="text-current">
            Delivery is paused for your organization. Pending deliveries are kept and will be sent when delivery resumes; waiting does not use up retry attempts.
          </AlertDescription>
        </Alert>
      )}
      <section aria-labelledby="webhook-endpoints-heading" aria-busy={endpoints.status === "loading"} className="space-y-3">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="webhook-endpoints-heading" className="text-lg font-medium">
              Endpoints
            </h2>
            <p className="text-sm text-muted-foreground">Up to 10 per tenant. Each endpoint receives only the events it subscribes to.</p>
          </div>
          {enabled && (
            <Button onClick={() => setDialog({ mode: "create" })} disabled={!typesReady || endpoints.status !== "ready"}>
              <Plus aria-hidden />
              New endpoint
            </Button>
          )}
        </header>

        {eventTypes.state.status === "error" && (
          <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 p-3 text-sm">
            <p>Event types could not be loaded: {describeProblem(eventTypes.state.problem).description}</p>
            <Button size="sm" variant="outline" onClick={eventTypes.reload}>
              Retry
            </Button>
          </div>
        )}

        {endpoints.status === "loading" && (
          <div className="space-y-2">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
        )}
        {endpoints.status === "error" && (
          <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 p-3 text-sm">
            <p className="font-medium text-destructive">{describeProblem(endpoints.problem).title}</p>
            <p className="text-muted-foreground">{describeProblem(endpoints.problem).description}</p>
            <Button size="sm" variant="outline" onClick={reload}>
              Retry
            </Button>
          </div>
        )}
        {endpoints.status === "ready" && endpoints.items.length === 0 && (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            {enabled ? "No webhook endpoints yet. Add one to send hiring events to your own systems." : "Webhooks are not available for your organization yet."}
          </p>
        )}
        {endpoints.status === "ready" && endpoints.items.length > 0 && (
          <ul className="space-y-2">
            {endpoints.items.map((endpoint) => (
              <EndpointRow
                key={endpoint.id}
                endpoint={endpoint}
                selected={endpoint.id === selectedId}
                toggling={toggling === endpoint.id}
                canEdit={typesReady}
                readOnly={!enabled}
                onShowDeliveries={() => setSelectedId(endpoint.id)}
                onEdit={() => setDialog({ mode: "edit", endpoint })}
                onToggle={() => void toggle(endpoint)}
                onRotate={() => setRotating(endpoint)}
                onDelete={() => setDeleting(endpoint)}
              />
            ))}
          </ul>
        )}
      </section>

      {selected && (
        <DeliveryLog
          key={selected.id}
          api={api}
          endpoint={selected}
          pollIntervalMs={pollIntervalMs}
          pollTimeoutMs={pollTimeoutMs}
          readOnly={!enabled}
          onRedelivered={() => void refreshEndpoint(selected.id)}
          onFeatureDisabled={onFeatureDisabled}
        />
      )}

      <EndpointDialog
        api={api}
        eventTypes={eventTypes.state.status === "ready" ? eventTypes.state.data.items : []}
        target={dialog}
        onOpenChange={(open) => !open && setDialog(null)}
        onStale={onStale}
        onFeatureDisabled={onFeatureDisabled}
        onSaved={(endpoint, secret) => {
          upsert(endpoint);
          setDialog(null);
          if (secret) setRevealed({ secret, host: hostOf(endpoint.url), reason: "created" });
          else toast.success(`Saved ${hostOf(endpoint.url)}.`);
        }}
      />
      <RotateSecretDialog
        api={api}
        endpoint={rotating}
        onOpenChange={(open) => !open && setRotating(null)}
        onStale={onStale}
        onRotated={(endpoint, secret) => {
          upsert(endpoint);
          setRotating(null);
          setRevealed(secret);
        }}
      />
      <DeleteEndpointDialog
        api={api}
        endpoint={deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        onStale={onStale}
        onDeleted={(endpoint) => {
          setDeleting(null);
          if (selectedId === endpoint.id) setSelectedId(null);
          setEndpoints((current) => (current.status === "ready" ? { status: "ready", items: current.items.filter((item) => item.id !== endpoint.id) } : current));
          toast.success(`Deleted ${hostOf(endpoint.url)}.`);
        }}
      />
      <SecretRevealDialog revealed={revealed} onDone={() => setRevealed(null)} />
    </div>
  );
}

function EndpointRow({
  endpoint,
  selected,
  toggling,
  canEdit,
  readOnly,
  onShowDeliveries,
  onEdit,
  onToggle,
  onRotate,
  onDelete,
}: {
  endpoint: WebhookEndpoint;
  selected: boolean;
  toggling: boolean;
  canEdit: boolean;
  readOnly: boolean;
  onShowDeliveries: () => void;
  onEdit: () => void;
  onToggle: () => void;
  onRotate: () => void;
  onDelete: () => void;
}) {
  const host = hostOf(endpoint.url);
  const reason = disabledReasonLabel(endpoint);
  const current = endpoint.secrets.find((secret) => secret.status === "current");
  const previous = endpoint.secrets.find((secret) => secret.status === "previous");
  return (
    <li data-endpoint-id={endpoint.id} aria-label={host} className={`space-y-3 rounded-lg border bg-card p-3 ${selected ? "ring-2 ring-ring/50" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <p className="font-mono text-sm break-all">{endpoint.url}</p>
          {endpoint.description && <p className="text-sm text-muted-foreground">{endpoint.description}</p>}
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge variant={endpoint.status === "enabled" ? "default" : "outline"}>{endpoint.status === "enabled" ? "Enabled" : "Disabled"}</Badge>
          {reason && <span className="text-xs text-muted-foreground">{reason}</span>}
          {endpoint.status === "enabled" && endpoint.consecutive_failures > 0 && (
            <span className="text-xs text-destructive">{endpoint.consecutive_failures} failures in a row</span>
          )}
        </div>
      </div>
      <ul aria-label="Subscribed events" className="flex flex-wrap gap-1">
        {endpoint.event_types.map((type) => (
          <li key={type}>
            <Badge variant="secondary" className="font-mono">
              {type}
            </Badge>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        {current ? `Signing secret created ${formatTimestamp(current.created_at)}` : "No active signing secret"}
        {previous?.expires_at && ` · previous secret expires ${formatTimestamp(previous.expires_at)}`}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={selected ? "secondary" : "outline"} onClick={onShowDeliveries} aria-pressed={selected} aria-label={`Deliveries for ${host}`}>
          <ListOrdered aria-hidden />
          Deliveries
        </Button>
        {!readOnly && (
          <Button size="sm" variant="outline" onClick={onEdit} disabled={!canEdit} aria-label={`Edit ${host}`}>
            <Pencil aria-hidden />
            Edit
          </Button>
        )}
        {(!readOnly || endpoint.status === "enabled") && (
          <Button size="sm" variant="outline" onClick={onToggle} disabled={toggling} aria-label={`${endpoint.status === "enabled" ? "Disable" : "Enable"} ${host}`}>
            <Power aria-hidden />
            {toggling ? "Saving…" : endpoint.status === "enabled" ? "Disable" : "Enable"}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={onRotate} aria-label={`Rotate secret for ${host}`}>
          <KeyRound aria-hidden />
          Rotate secret
        </Button>
        <Button size="sm" variant="ghost" className="text-destructive" onClick={onDelete} aria-label={`Delete ${host}`}>
          <Trash2 aria-hidden />
          Delete
        </Button>
      </div>
    </li>
  );
}

function DeleteEndpointDialog({
  api,
  endpoint,
  onOpenChange,
  onDeleted,
  onStale,
}: {
  api: ApiClient;
  endpoint: WebhookEndpoint | null;
  onOpenChange: (open: boolean) => void;
  onDeleted: (endpoint: WebhookEndpoint) => void;
  onStale: (problem: ProblemDetails) => void;
}) {
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function changeOpen(open: boolean) {
    if (!open) setProblem(null);
    onOpenChange(open);
  }

  async function confirm() {
    if (!endpoint) return;
    setSubmitting(true);
    setProblem(null);
    const result = await settle(
      api.DELETE("/v1/webhook-endpoints/{endpoint_id}", {
        params: { path: { endpoint_id: endpoint.id }, header: { "If-Match": ifMatch(endpoint.version) } },
      }),
    );
    setSubmitting(false);
    if (result.ok) onDeleted(endpoint);
    else if (isStale(result.problem)) onStale(result.problem);
    else setProblem(result.problem);
  }

  return (
    <Dialog open={endpoint !== null} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete endpoint?</DialogTitle>
          <DialogDescription>
            {endpoint ? `${hostOf(endpoint.url)} stops receiving events. ` : ""}Its signing secrets are destroyed and pending deliveries are cancelled. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {problem && <FormProblem problem={problem} />}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button type="button" variant="destructive" disabled={submitting} onClick={() => void confirm()}>
            {submitting ? "Deleting…" : "Delete endpoint"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
