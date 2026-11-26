"use client";

import { Download, FileText, Upload } from "lucide-react";
import { useCallback, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { CONTROL_CLASS, Field, FormProblem } from "@/components/pipeline/form-fields";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BROWSER_API_BASE, settle, type ApiClient } from "@/lib/api/client";
import type { ProblemDetails } from "@/lib/api/problem";
import {
  allowedTypesLabel,
  contentTypeLabel,
  DOCUMENT_TYPE_LABELS,
  DOCUMENT_TYPES,
  documentTypeLabel,
  downloadHref,
  formatBytes,
  formatTimestamp,
  uploadError,
  type AttachmentPolicy,
} from "@/lib/candidates/detail";
import { useResource } from "@/lib/candidates/use-resource";

import { Panel, PanelProblem } from "./panel";

export function AttachmentsPanel({
  api,
  candidateCaseId,
  onUploaded,
}: {
  api: ApiClient;
  candidateCaseId: string;
  onUploaded: () => void;
}) {
  const attachments = useResource(
    useCallback(
      () => settle(api.GET("/v1/candidate-cases/{candidate_case_id}/attachments", { params: { path: { candidate_case_id: candidateCaseId } } })),
      [api, candidateCaseId],
    ),
  );
  const policy = useResource(useCallback(() => settle(api.GET("/v1/attachment-policy")), [api]));
  const listState = attachments.state;
  const forbidden = listState.status === "error" && listState.problem.status === 403;

  return (
    <Panel id="attachments" title="Attachments" busy={listState.status === "loading"}>
      {listState.status === "loading" && <Skeleton className="h-12" />}
      {listState.status === "error" && <PanelProblem problem={listState.problem} what="attachments" onRetry={attachments.reload} />}
      {listState.status === "ready" &&
        (listState.data.length === 0 ? (
          <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">No attachments yet.</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {listState.data.map((attachment) => (
              <li key={attachment.id} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
                <div className="flex min-w-0 items-center gap-2">
                  <FileText aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0">
                    <p className="truncate font-medium">{attachment.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {documentTypeLabel(attachment.document_type)} · {contentTypeLabel(attachment.content_type)} ·{" "}
                      {formatBytes(attachment.size_bytes)} · {formatTimestamp(attachment.created_at)}
                    </p>
                  </div>
                </div>
                <Button asChild size="sm" variant="outline">
                  <a href={downloadHref(BROWSER_API_BASE, candidateCaseId, attachment.id)} rel="noopener" aria-label={`Download ${attachment.filename}`}>
                    <Download aria-hidden />
                    Download
                  </a>
                </Button>
              </li>
            ))}
          </ul>
        ))}
      {!forbidden && (
        <>
          {policy.state.status === "loading" && <Skeleton className="h-24" />}
          {policy.state.status === "error" && <PanelProblem problem={policy.state.problem} what="the upload rules" onRetry={policy.reload} />}
          {policy.state.status === "ready" && (
            <UploadForm
              api={api}
              candidateCaseId={candidateCaseId}
              policy={policy.state.data}
              onUploaded={() => {
                attachments.reload();
                onUploaded();
              }}
            />
          )}
        </>
      )}
    </Panel>
  );
}

function UploadForm({
  api,
  candidateCaseId,
  policy,
  onUploaded,
}: {
  api: ApiClient;
  candidateCaseId: string;
  policy: AttachmentPolicy;
  onUploaded: () => void;
}) {
  const [documentType, setDocumentType] = useState<string>("resume");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemDetails | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const invalid = uploadError(file, documentType, policy);
    setError(invalid);
    setProblem(null);
    if (invalid || !file) {
      fileRef.current?.focus();
      return;
    }
    setUploading(true);
    const result = await settle(
      api.POST("/v1/candidate-cases/{candidate_case_id}/attachments", {
        params: { path: { candidate_case_id: candidateCaseId } },
        body: { document_type: documentType, file: file.name },
        bodySerializer: () => {
          const form = new FormData();
          form.append("document_type", documentType);
          form.append("file", file, file.name);
          return form;
        },
      }),
    );
    setUploading(false);
    if (result.ok) {
      toast.success(`Uploaded ${result.data.filename}.`);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onUploaded();
    } else {
      setProblem(result.problem);
    }
  }

  const hint = `${allowedTypesLabel(policy)}, up to ${formatBytes(policy.max_bytes)}.`;

  return (
    <form onSubmit={(event) => void submit(event)} noValidate aria-label="Upload attachment" className="space-y-3 border-t pt-3">
      <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
        <Field id="attachment-type" label="Document type">
          <select id="attachment-type" className={CONTROL_CLASS} value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
            {DOCUMENT_TYPES.map((value) => (
              <option key={value} value={value}>
                {DOCUMENT_TYPE_LABELS[value]}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid gap-1.5">
          <label htmlFor="attachment-file" className="text-sm font-medium">
            File
          </label>
          <input
            id="attachment-file"
            ref={fileRef}
            type="file"
            accept={policy.allowed_content_types.join(",")}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "attachment-file-error attachment-file-hint" : "attachment-file-hint"}
            className="text-sm file:mr-3 file:rounded-md file:border file:border-input file:bg-background file:px-2.5 file:py-1 file:text-sm"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setError(null);
              setProblem(null);
            }}
          />
          <p id="attachment-file-hint" className="text-xs text-muted-foreground">
            {hint}
          </p>
          {error && (
            <p id="attachment-file-error" role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </div>
      </div>
      {problem && <FormProblem problem={problem} />}
      <Button type="submit" size="sm" disabled={uploading}>
        <Upload aria-hidden />
        {uploading ? "Uploading…" : "Upload"}
      </Button>
    </form>
  );
}
