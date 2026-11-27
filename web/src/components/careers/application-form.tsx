"use client";
import { useState, type FormEvent } from "react";
import type { Consent, CareersListing } from "@/lib/careers/public-api";
import { Button } from "@/components/ui/button";

export function ApplicationForm({
  slug,
  requisitionId,
  consent,
  policy,
}: {
  slug: string;
  requisitionId: string;
  consent: Consent;
  policy: CareersListing["upload_policy"];
}) {
  const [received, setReceived] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const cv = data.get("cv");
    if (
      !(cv instanceof File) ||
      !cv.size ||
      cv.size > policy.max_bytes ||
      !policy.content_types.includes(cv.type)
    ) {
      setError("Choose a PDF or DOCX within the displayed size limit.");
      return;
    }
    setPending(true);
    setError("");
    try {
      const response = await fetch(
        `/api/public/careers/${encodeURIComponent(slug)}/${encodeURIComponent(requisitionId)}`,
        { method: "POST", body: data },
      );
      if (response.status === 202) setReceived(true);
      else
        setError(
          (
            {
              413: "Your application is too large. Choose a smaller CV.",
              422: "Check your details and CV. Reload this page if the consent text has changed.",
              429: "Too many applications. Please try again later.",
              503: "Applications are temporarily unavailable. Please try again shortly.",
              404: "This role is no longer available.",
            } as Record<number, string>
          )[response.status] ??
            "We could not receive your application. Please try again.",
        );
    } catch {
      setError("We could not connect. Please try again.");
    } finally {
      setPending(false);
    }
  }
  if (received)
    return (
      <div role="status">
        <h2 className="text-2xl font-semibold">Application received</h2>
        <p className="mt-3">Thank you for your interest.</p>
      </div>
    );
  return (
    <form onSubmit={submit} className="space-y-6">
      <label className="block">
        First name
        <input
          className="mt-2 block w-full rounded-md border p-2"
          name="first_name"
          required
          minLength={1}
          maxLength={100}
          autoComplete="given-name"
        />
      </label>
      <label className="block">
        Last name
        <input
          className="mt-2 block w-full rounded-md border p-2"
          name="last_name"
          required
          minLength={1}
          maxLength={100}
          autoComplete="family-name"
        />
      </label>
      <label className="block">
        Email
        <input
          className="mt-2 block w-full rounded-md border p-2"
          name="email"
          type="email"
          required
          maxLength={320}
          autoComplete="email"
        />
      </label>
      <label className="block">
        CV (PDF or DOCX, up to {Math.round(policy.max_bytes / 1024 / 1024)} MiB)
        <input
          className="mt-2 block w-full rounded-md border p-2"
          name="cv"
          type="file"
          accept={policy.content_types.join(",")}
          required
        />
      </label>
      <div className="sr-only">
        <label>
          Leave this field empty
          <input
            className="mt-2 block w-full rounded-md border p-2"
            name="website"
            tabIndex={-1}
            autoComplete="off"
          />
        </label>
      </div>
      <section
        aria-label="Application consent"
        className="rounded-lg border p-5"
      >
        <p className="whitespace-pre-wrap">{consent.text}</p>
        <input type="hidden" name="consent_version" value={consent.version} />
        <label className="mt-4 flex items-start gap-3">
          <input
            className="mt-1"
            type="checkbox"
            name="consent_accepted"
            value="true"
            required
          />
          I agree to this processing of my application.
        </label>
      </section>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending}>
        {pending ? "Sending…" : "Send application"}
      </Button>
    </form>
  );
}
