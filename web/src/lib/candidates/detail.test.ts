import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { describeEvent, DOCUMENT_TYPES, formatBytes, uploadError } from "./detail";

const POLICY = { max_bytes: 10, allowed_content_types: ["application/pdf"] };

function backendDocumentTypes(): string[] {
  const source = readFileSync(
    fileURLToPath(new URL("../../../../app/modules/attachments/application/attachment_service.py", import.meta.url)),
    "utf8",
  );
  const set = source.match(/ALLOWED_DOCUMENT_TYPES = frozenset\(\{([^}]*)\}\)/)![1];
  return [...set.matchAll(/"([a-z_]+)"/g)].map(([, value]) => value).sort();
}

describe("candidate detail helpers", () => {
  it("mirrors the backend document types", () => {
    expect([...DOCUMENT_TYPES].sort()).toEqual(backendDocumentTypes());
  });

  it("validates uploads against the served policy", () => {
    expect(uploadError(new File(["%PDF-"], "a.pdf", { type: "application/pdf" }), "resume", POLICY)).toBeNull();
    expect(uploadError(new File(["%PDF-"], "a.pdf", { type: "application/pdf" }), "invoice", POLICY)).toBe("Choose a document type.");
    expect(uploadError(new File(["x"], "a.docx", { type: "" }), "resume", POLICY)).toBe("Only PDF files can be uploaded.");
    expect(uploadError(new File(["%PDF-"], "A.PDF", { type: "application/pdf" }), "resume", POLICY)).toBeNull();
    expect(uploadError(new File(["%PDF-123456"], "a.pdf", { type: "application/pdf" }), "resume", POLICY)).toBe("The file is 11 B; the limit is 10 B.");
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });

  it("describes timeline events from allowlisted metadata only", () => {
    expect(describeEvent({ action: "candidate_case.created", metadata: { stage: "applied" } })).toEqual({ title: "Candidate created", detail: "Started in Applied" });
    expect(describeEvent({ action: "candidate_case.stage_transitioned", metadata: {} })).toEqual({ title: "Stage changed", detail: null });
    expect(describeEvent({ action: "candidate_case.legal_hold_set", metadata: {} }).title).toBe("Legal hold placed");
    expect(describeEvent({ action: "interview.scheduled", metadata: {} })).toEqual({ title: "interview.scheduled", detail: null });
  });
});
