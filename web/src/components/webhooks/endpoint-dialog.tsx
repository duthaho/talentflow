"use client";

import { useState, type FormEvent } from "react";

import { fieldError, FormProblem, TextField } from "@/components/pipeline/form-fields";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { settle, type ApiClient } from "@/lib/api/client";
import { ifMatch } from "@/lib/api/precondition";
import { isStale } from "@/lib/webhooks/format";
import { isFeatureDisabled, type ProblemDetails } from "@/lib/api/problem";
import {
  DESCRIPTION_MAX,
  URL_MAX,
  validateEndpointDraft,
  type EventType,
  type PlaintextSecret,
  type WebhookEndpoint,
  type WebhookEventType,
} from "@/lib/webhooks/format";

export type EndpointDialogTarget = { mode: "create" } | { mode: "edit"; endpoint: WebhookEndpoint };

type Draft = { url: string; description: string; eventTypes: EventType[]; enabled: boolean };

function draftFor(target: EndpointDialogTarget): Draft {
  if (target.mode === "create") return { url: "", description: "", eventTypes: [], enabled: true };
  const { endpoint } = target;
  return { url: endpoint.url, description: endpoint.description ?? "", eventTypes: [...endpoint.event_types], enabled: endpoint.status === "enabled" };
}

export function EndpointDialog({
  api,
  eventTypes,
  target,
  onOpenChange,
  onSaved,
  onStale,
  onFeatureDisabled,
}: {
  api: ApiClient;
  eventTypes: WebhookEventType[];
  target: EndpointDialogTarget | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (endpoint: WebhookEndpoint, secret: PlaintextSecret | null) => void;
  onStale: (problem: ProblemDetails) => void;
  onFeatureDisabled: () => void;
}) {
  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        {target && <EndpointForm key={target.mode === "edit" ? `${target.endpoint.id}:${target.endpoint.version}` : "create"} api={api} eventTypes={eventTypes} target={target} onSaved={onSaved} onStale={onStale} onFeatureDisabled={onFeatureDisabled} />}
      </DialogContent>
    </Dialog>
  );
}

function EndpointForm({
  api,
  eventTypes,
  target,
  onSaved,
  onStale,
  onFeatureDisabled,
}: {
  api: ApiClient;
  eventTypes: WebhookEventType[];
  target: EndpointDialogTarget;
  onSaved: (endpoint: WebhookEndpoint, secret: PlaintextSecret | null) => void;
  onStale: (problem: ProblemDetails) => void;
  onFeatureDisabled: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFor(target));
  const [clientErrors, setClientErrors] = useState<ReturnType<typeof validateEndpointDraft>>({});
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const creating = target.mode === "create";

  function toggleType(type: EventType, checked: boolean) {
    setDraft((current) => ({
      ...current,
      eventTypes: checked ? [...current.eventTypes, type] : current.eventTypes.filter((item) => item !== type),
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validateEndpointDraft(draft);
    setClientErrors(errors);
    setProblem(null);
    if (Object.keys(errors).length > 0) return;
    const body = {
      url: draft.url.trim(),
      description: draft.description.trim() || null,
      event_types: draft.eventTypes,
      enabled: draft.enabled,
    };
    setSubmitting(true);
    if (target.mode === "create") {
      const result = await settle(api.POST("/v1/webhook-endpoints", { body }));
      setSubmitting(false);
      if (result.ok) {
        const { secret, ...endpoint } = result.data;
        onSaved(endpoint, secret);
      } else if (isFeatureDisabled(result.problem)) onFeatureDisabled();
      else setProblem(result.problem);
      return;
    }
    const result = await settle(
      api.PATCH("/v1/webhook-endpoints/{endpoint_id}", {
        params: { path: { endpoint_id: target.endpoint.id }, header: { "If-Match": ifMatch(target.endpoint.version) } },
        body,
      }),
    );
    setSubmitting(false);
    if (result.ok) onSaved(result.data, null);
    else if (isStale(result.problem)) onStale(result.problem);
    else if (isFeatureDisabled(result.problem)) onFeatureDisabled();
    else setProblem(result.problem);
  }

  const urlError = clientErrors.url ?? fieldError(problem, "url");
  const descriptionError = clientErrors.description ?? fieldError(problem, "description");
  const typesError = clientErrors.event_types ?? problem?.errors?.find((error) => error.pointer.includes("/event_types"))?.detail;
  const formLevelProblem = problem && !urlError && !descriptionError && !typesError ? problem : null;

  return (
    <>
      <DialogHeader>
        <DialogTitle>{creating ? "New webhook endpoint" : "Edit webhook endpoint"}</DialogTitle>
        <DialogDescription>
          {creating
            ? "TalentFlow signs each request. You see the signing secret once, right after you create the endpoint."
            : "Changes apply to the next attempt of every pending delivery."}
        </DialogDescription>
      </DialogHeader>
      <form noValidate onSubmit={(event) => void submit(event)} className="grid gap-4">
        <TextField
          id="webhook-url"
          label="Receiver URL"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="https://hooks.example.com/talentflow"
          maxLength={URL_MAX}
          value={draft.url}
          onChange={(event) => setDraft((current) => ({ ...current, url: event.target.value }))}
          error={urlError}
        />
        <TextField
          id="webhook-description"
          label="Description (optional)"
          autoComplete="off"
          maxLength={DESCRIPTION_MAX}
          value={draft.description}
          onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
          error={descriptionError}
        />
        <fieldset className="grid gap-2" aria-describedby={typesError ? "webhook-events-error" : undefined} aria-invalid={typesError ? true : undefined}>
          <legend className="mb-1 text-sm font-medium">Events</legend>
          {eventTypes.length === 0 && <p className="text-sm text-muted-foreground">No event types are available.</p>}
          {eventTypes.map((item) => {
            const id = `webhook-event-${item.type}`;
            return (
              <div key={item.type} className="flex items-start gap-2">
                <input
                  id={id}
                  type="checkbox"
                  className="mt-1 size-4 accent-primary"
                  checked={draft.eventTypes.includes(item.type)}
                  onChange={(event) => toggleType(item.type, event.target.checked)}
                  aria-describedby={`${id}-description`}
                />
                <label htmlFor={id} className="grid text-sm">
                  <span className="font-mono">{item.type}</span>
                  <span id={`${id}-description`} className="text-muted-foreground">
                    {item.description}
                    {item.status !== "active" && ` (${item.status})`}
                  </span>
                </label>
              </div>
            );
          })}
          {typesError && (
            <p id="webhook-events-error" className="text-xs text-destructive">
              {typesError}
            </p>
          )}
        </fieldset>
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={draft.enabled}
            onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
          />
          Enabled
        </label>
        {formLevelProblem && <FormProblem problem={formLevelProblem} />}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Saving…" : creating ? "Create endpoint" : "Save changes"}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
