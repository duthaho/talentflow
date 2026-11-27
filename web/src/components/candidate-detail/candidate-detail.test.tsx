// @vitest-environment jsdom
import { File as NodeFile } from "node:buffer";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { Role } from "@/lib/actor/actor";

import {
  apiProblem,
  attachment,
  auditEvent,
  CASE,
  DOCX,
  fakeDetailBackend,
  PDF,
} from "../../../test/candidate-detail-fake";
import { ROLE_PERMISSIONS } from "../../../test/role-permissions";
import { CandidateDetail, type DetailPermissions } from "./candidate-detail";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function permissionsFor(role: Role): DetailPermissions {
  const granted = ROLE_PERMISSIONS[role];
  return {
    attachments: granted.includes("candidate:attachment"),
    audit: granted.includes("audit:read"),
    retention: granted.includes("retention:manage"),
  };
}

function panel(id: string): HTMLElement {
  return document.querySelector<HTMLElement>(`section[data-panel="${id}"]`)!;
}

async function settled() {
  await waitFor(() => expect(document.querySelectorAll('[aria-busy="true"]')).toHaveLength(0));
}

async function renderAs(role: Role, options: Omit<Parameters<typeof fakeDetailBackend>[0], "permissions"> = {}, permissions = permissionsFor(role)) {
  const backend = fakeDetailBackend({ permissions: ROLE_PERMISSIONS[role], ...options });
  render(<CandidateDetail api={backend.api} candidateCaseId={CASE.id} currentUserId="user-me" permissions={permissions} />);
  await settled();
  return backend;
}

function paths(backend: ReturnType<typeof fakeDetailBackend>) {
  return backend.requests.map((request) => `${request.method} ${new URL(request.url).pathname}`);
}

async function chooseFile(file: File) {
  await userEvent.upload(screen.getByLabelText("File"), file, { applyAccept: false });
}

async function submitUpload() {
  await userEvent.click(within(panel("attachments")).getByRole("button", { name: "Upload" }));
}

function pdf(name = "cv.pdf", bytes = 100) {
  return file(["%PDF-".padEnd(bytes, "x")], name, PDF);
}

// jsdom swaps in its own File and FormData, which undici (the Request implementation in tests)
// serializes with the filename "blob". Use Node's classes so the multipart body matches a browser's.
const NodeFormData = (await new Response(new URLSearchParams()).formData()).constructor as typeof FormData;

function file(parts: string[], name: string, type: string): File {
  return new NodeFile(parts, name, { type }) as unknown as File;
}

beforeAll(() => vi.stubGlobal("FormData", NodeFormData));
afterAll(() => vi.unstubAllGlobals());

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
  vi.mocked(toast.success).mockClear();
});

describe("CandidateDetail", () => {
  it("shows profile, stage, attachments, timeline and retention status to a tenant admin", async () => {
    const backend = await renderAs("tenant_admin", {
      attachments: [attachment("att-1", { filename: "ada-cv.pdf" })],
      events: [
        auditEvent("e2", { action: "candidate_attachment.uploaded", aggregate_type: "candidate_attachment", aggregate_id: "att-1", metadata: { document_type: "resume", content_type: PDF, size_bytes: 2048 } }),
        auditEvent("e1", { actor_id: "user-other-123456" }),
      ],
      hold: { held: true, reason: "Pending litigation", placed_at: "2026-11-22T08:00:00Z", placed_by: "user-me" },
      retentionDays: 90,
    });

    expect(screen.getByRole("heading", { level: 1, name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByLabelText("Stage: Screening")).toBeInTheDocument();
    expect(screen.getByText("ada@example.test")).toBeInTheDocument();

    const download = within(panel("attachments")).getByRole("link", { name: /Download ada-cv.pdf/ });
    expect(download).toHaveAttribute("href", "/api/tf/v1/candidate-cases/case-1/attachments/att-1/download");
    expect(within(panel("attachments")).getByText(/Resume · PDF · 2\.0 KB/)).toBeInTheDocument();

    const timeline = within(panel("timeline"));
    const items = timeline.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Attachment uploaded");
    expect(items[0]).toHaveTextContent("You");
    expect(items[1]).toHaveTextContent("Applied → Screening");
    expect(items[1]).toHaveTextContent("User user-oth");

    const retention = within(panel("retention"));
    expect(retention.getByText(/On hold/)).toBeInTheDocument();
    expect(retention.getByText("Pending litigation")).toBeInTheDocument();
    expect(retention.getByText(/anonymized 90 days after they close/)).toBeInTheDocument();
    expect(paths(backend)).toContain("GET /v1/candidate-cases/case-1/legal-hold");
  });

  it("shows no hold and an unset retention policy", async () => {
    await renderAs("recruiter", { retentionDays: null });
    const retention = within(panel("retention"));
    expect(retention.getByText("No legal hold")).toBeInTheDocument();
    expect(retention.getByText(/No retention policy is set/)).toBeInTheDocument();
    expect(within(panel("attachments")).getByText("No attachments yet.")).toBeInTheDocument();
    expect(within(panel("timeline")).getByText("No recorded activity yet.")).toBeInTheDocument();
  });

  it("shows a not-found state for an unknown or foreign case", async () => {
    await renderAs("tenant_admin", { candidate: null });
    expect(screen.getByRole("heading", { name: "Candidate not found" })).toBeInTheDocument();
    expect(panel("attachments")).toBeNull();
  });

  it("offers a retry when the case fails to load", async () => {
    let failures = 1;
    await renderAs("tenant_admin", {
      override: (request) => (new URL(request.url).pathname === "/v1/candidate-cases/case-1" && failures-- > 0 ? apiProblem(503, "service-unavailable", "Down") : undefined),
    });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await settled();
    expect(screen.getByRole("heading", { level: 1, name: "Ada Lovelace" })).toBeInTheDocument();
  });

  it("loads older timeline pages with the cursor", async () => {
    const events = Array.from({ length: 25 }, (_, index) => auditEvent(`e${String(index).padStart(2, "0")}`));
    const backend = await renderAs("tenant_admin", { events });
    expect(within(panel("timeline")).getAllByRole("listitem")).toHaveLength(20);
    await userEvent.click(screen.getByRole("button", { name: "Show older activity" }));
    await settled();
    expect(within(panel("timeline")).getAllByRole("listitem")).toHaveLength(25);
    expect(screen.queryByRole("button", { name: "Show older activity" })).not.toBeInTheDocument();
    const second = backend.requests.filter((request) => request.url.includes("audit-events")).at(-1)!;
    expect(new URL(second.url).searchParams.get("cursor")).toBe("e19");
  });

  describe("permissions", () => {
    it("hides attachments, timeline and retention from a hiring manager without calling those APIs", async () => {
      const backend = await renderAs("hiring_manager");
      expect(screen.getByRole("heading", { level: 1, name: "Ada Lovelace" })).toBeInTheDocument();
      expect(within(panel("attachments")).getByText(/can't view or upload attachments/)).toBeInTheDocument();
      expect(within(panel("timeline")).getByText(/can't view the audit timeline/)).toBeInTheDocument();
      expect(panel("retention")).toBeNull();
      expect(paths(backend)).toEqual(["GET /v1/candidate-cases/case-1"]);
    });

    it("shows an auditor the timeline but not attachments or retention", async () => {
      await renderAs("auditor", { events: [auditEvent("e1")] });
      expect(within(panel("timeline")).getByText("Stage changed")).toBeInTheDocument();
      expect(within(panel("attachments")).getByText(/can't view or upload attachments/)).toBeInTheDocument();
      expect(panel("retention")).toBeNull();
      expect(screen.queryByLabelText("File")).not.toBeInTheDocument();
    });

    it("renders a no-access state when the API answers 403 despite the session permissions", async () => {
      await renderAs("hiring_manager", {}, { attachments: true, audit: true, retention: true });
      expect(within(panel("attachments")).getByText(/can't view attachments/)).toBeInTheDocument();
      expect(within(panel("attachments")).queryByLabelText("File")).not.toBeInTheDocument();
      expect(within(panel("timeline")).getByText(/can't view the audit timeline/)).toBeInTheDocument();
      expect(within(panel("retention")).getByText(/can't view the legal hold/)).toBeInTheDocument();
      expect(within(panel("retention")).getByText(/can't view the retention policy/)).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  describe("upload", () => {
    function posts(backend: ReturnType<typeof fakeDetailBackend>) {
      return backend.requests.filter((request) => request.method === "POST");
    }

    it("uploads a valid file as multipart and refreshes the list and timeline", async () => {
      const backend = await renderAs("recruiter");
      await userEvent.selectOptions(screen.getByLabelText("Document type"), "cover_letter");
      await chooseFile(pdf("letter.pdf"));
      await submitUpload();
      await settled();

      const [post] = posts(backend);
      const form = await post.formData();
      expect(form.get("document_type")).toBe("cover_letter");
      expect((form.get("file") as File).name).toBe("letter.pdf");
      expect(within(panel("attachments")).getByRole("link", { name: /Download letter.pdf/ })).toBeInTheDocument();
      expect(toast.success).toHaveBeenCalledWith("Uploaded letter.pdf.");
      expect(backend.requests.filter((request) => request.url.includes("audit-events"))).toHaveLength(2);
    });

    it.each([
      ["no file", null, "Choose a file to upload."],
      ["a disallowed type", file(["png"], "photo.png", "image/png"), "Only DOCX or PDF files can be uploaded."],
      ["a mismatched extension", file(["%PDF-"], "cv.docx", PDF), "A PDF file must end in .pdf."],
      ["an empty file", file([], "cv.pdf", PDF), "The file is empty."],
      ["a file over the limit", pdf("big.pdf", 2048), "The file is 2.0 KB; the limit is 1.0 KB."],
    ])("rejects %s before calling the API", async (_label, file, message) => {
      const backend = await renderAs("recruiter");
      if (file) await chooseFile(file);
      await submitUpload();
      expect(within(panel("attachments")).getByRole("alert")).toHaveTextContent(message);
      expect(screen.getByLabelText("File")).toHaveAttribute("aria-invalid", "true");
      expect(posts(backend)).toHaveLength(0);
    });

    it("accepts a DOCX file", async () => {
      const backend = await renderAs("recruiter");
      await chooseFile(file(["PK\u0003\u0004"], "cv.docx", DOCX));
      await submitUpload();
      await settled();
      expect(posts(backend)).toHaveLength(1);
    });

    it.each([
      [422, "validation-error", "Attachment content does not match PDF type", "Attachment content does not match PDF type"],
      [503, "service-unavailable", "Attachment malware scanner is unavailable", "Attachment malware scanner is unavailable"],
      [403, "forbidden", "Forbidden", "You don't have access"],
    ])("shows the API's %i response and keeps the list unchanged", async (status, slug, detail, shown) => {
      await renderAs("recruiter", {
        override: (request) => (request.method === "POST" ? apiProblem(status, slug, detail) : undefined),
      });
      await chooseFile(pdf());
      await submitUpload();
      await settled();
      const alert = within(panel("attachments")).getByRole("alert");
      expect(alert).toHaveTextContent(shown);
      expect(alert).toHaveTextContent("Reference: corr-1");
      expect(within(panel("attachments")).getByText("No attachments yet.")).toBeInTheDocument();
      expect(toast.success).not.toHaveBeenCalled();
    });

    it("blocks uploads while the upload rules cannot be loaded, then recovers on retry", async () => {
      let failures = 1;
      await renderAs("recruiter", {
        override: (request) => (new URL(request.url).pathname === "/v1/attachment-policy" && failures-- > 0 ? apiProblem(503, "service-unavailable", "Down") : undefined),
      });
      expect(screen.queryByLabelText("File")).not.toBeInTheDocument();
      await userEvent.click(within(panel("attachments")).getByRole("button", { name: "Retry" }));
      await settled();
      expect(screen.getByLabelText("File")).toBeInTheDocument();
      expect(screen.getByText("DOCX or PDF, up to 1.0 KB.")).toBeInTheDocument();
    });
  });
});

it("shows exact server consent as plain text and hides the panel for staff cases", async () => {
  const text = '<script>alert("test")</script> Demo retention wording';
  await renderAs("hiring_manager", { candidate: { ...CASE, source: "careers", consent: { version: "careers-v1", text, accepted_at: "2026-11-20T09:00:00Z" } } });
  expect(screen.getByText("Source: careers page")).toBeInTheDocument();
  expect(panel("consent")).toHaveTextContent(text);
  expect(panel("consent").querySelector("script")).toBeNull();
});
