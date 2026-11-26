import type { components } from "@/lib/api/schema";
import { isStage, STAGE_LABELS } from "@/lib/pipeline/stages";

export type CandidateCaseDetail = components["schemas"]["CandidateCaseDetailResponse"];
export type Attachment = components["schemas"]["AttachmentResponse"];
export type AttachmentPolicy = components["schemas"]["AttachmentPolicyResponse"];
export type CaseAuditEvent = components["schemas"]["CaseAuditEventItem"];
export type LegalHold = components["schemas"]["LegalHoldResponse"];

// Mirror of ALLOWED_DOCUMENT_TYPES in app/modules/attachments/application/attachment_service.py;
// detail.test.ts fails when the two drift. Size and content-type limits come from GET /v1/attachment-policy.
export const DOCUMENT_TYPES = ["resume", "cover_letter", "portfolio", "other"] as const;
export type DocumentType = (typeof DOCUMENT_TYPES)[number];

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  resume: "Resume",
  cover_letter: "Cover letter",
  portfolio: "Portfolio",
  other: "Other",
};

const EXTENSION_BY_CONTENT_TYPE: Record<string, { extension: string; label: string }> = {
  "application/pdf": { extension: ".pdf", label: "PDF" },
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": { extension: ".docx", label: "DOCX" },
};

export function documentTypeLabel(value: unknown): string {
  return typeof value === "string" ? (DOCUMENT_TYPE_LABELS[value as DocumentType] ?? value) : "Document";
}

export function contentTypeLabel(contentType: unknown): string {
  return typeof contentType === "string" ? (EXTENSION_BY_CONTENT_TYPE[contentType]?.label ?? contentType) : "file";
}

export function stageLabel(stage: unknown): string {
  return typeof stage === "string" && isStage(stage) ? STAGE_LABELS[stage] : String(stage);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(date) + " UTC";
}

export function actorLabel(actorId: string | null | undefined, currentUserId: string): string {
  if (!actorId) return "Unknown user";
  return actorId === currentUserId ? "You" : `User ${actorId.slice(0, 8)}`;
}

export function allowedTypesLabel(policy: AttachmentPolicy): string {
  return policy.allowed_content_types.map(contentTypeLabel).join(" or ");
}

// Early feedback only: the API re-checks everything, including the file signature.
export function uploadError(file: File | null, documentType: string, policy: AttachmentPolicy): string | null {
  if (!(DOCUMENT_TYPES as readonly string[]).includes(documentType)) return "Choose a document type.";
  if (!file) return "Choose a file to upload.";
  if (!policy.allowed_content_types.includes(file.type)) return `Only ${allowedTypesLabel(policy)} files can be uploaded.`;
  const expected = EXTENSION_BY_CONTENT_TYPE[file.type]?.extension;
  if (expected && !file.name.toLowerCase().endsWith(expected)) return `A ${contentTypeLabel(file.type)} file must end in ${expected}.`;
  if (file.size === 0) return "The file is empty.";
  if (file.size > policy.max_bytes) return `The file is ${formatBytes(file.size)}; the limit is ${formatBytes(policy.max_bytes)}.`;
  return null;
}

export function downloadHref(apiBase: string, candidateCaseId: string, attachmentId: string): string {
  return `${apiBase}/v1/candidate-cases/${encodeURIComponent(candidateCaseId)}/attachments/${encodeURIComponent(attachmentId)}/download`;
}

export type EventView = { title: string; detail: string | null };

export function describeEvent(event: Pick<CaseAuditEvent, "action" | "metadata">): EventView {
  const meta = event.metadata ?? {};
  switch (event.action) {
    case "candidate_case.created":
      return { title: "Candidate created", detail: meta.stage ? `Started in ${stageLabel(meta.stage)}` : null };
    case "candidate_case.stage_transitioned":
      return {
        title: "Stage changed",
        detail: meta.from_stage && meta.to_stage ? `${stageLabel(meta.from_stage)} → ${stageLabel(meta.to_stage)}` : null,
      };
    case "candidate_case.legal_hold_set":
      return { title: "Legal hold placed", detail: null };
    case "candidate_case.legal_hold_released":
      return { title: "Legal hold released", detail: null };
    case "candidate_case.retention_purged":
      return { title: "Personal data purged by retention", detail: null };
    case "candidate_attachment.uploaded": {
      const parts = [
        meta.document_type ? documentTypeLabel(meta.document_type) : null,
        meta.content_type ? contentTypeLabel(meta.content_type) : null,
        typeof meta.size_bytes === "number" ? formatBytes(meta.size_bytes) : null,
      ].filter(Boolean);
      return { title: "Attachment uploaded", detail: parts.length ? parts.join(" · ") : null };
    }
    case "candidate_attachment.downloaded":
      return { title: "Attachment downloaded", detail: null };
    default:
      return { title: event.action, detail: null };
  }
}
