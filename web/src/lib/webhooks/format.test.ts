import { describe, expect, it } from "vitest";

import { fakeDelivery } from "../../../test/webhooks-fake";

import { canRedeliver, disabledReasonLabel, hostOf, lastResponseLabel, redeliveryOutcome, validateEndpointDraft } from "./format";

describe("webhook formatting", () => {
  it("allows redelivery only from a terminal state to an enabled endpoint", () => {
    expect(canRedeliver({ status: "dead_lettered" }, { status: "enabled" })).toBe(true);
    expect(canRedeliver({ status: "cancelled" }, { status: "enabled" })).toBe(true);
    expect(canRedeliver({ status: "pending" }, { status: "enabled" })).toBe(false);
    expect(canRedeliver({ status: "succeeded" }, { status: "disabled" })).toBe(false);
  });

  it("explains every disabled reason", () => {
    expect(disabledReasonLabel({ status: "enabled", disabled_reason: null })).toBeNull();
    expect(disabledReasonLabel({ status: "disabled", disabled_reason: "gone" })).toMatch(/410 Gone/);
    expect(disabledReasonLabel({ status: "disabled", disabled_reason: null })).toBe("Disabled");
  });

  it("prefers the HTTP status, then the transport error", () => {
    expect(lastResponseLabel({ last_status_code: 404, last_error_code: "http_status" })).toBe("HTTP 404");
    expect(lastResponseLabel({ last_status_code: null, last_error_code: "tls_error" })).toBe("TLS error");
    expect(lastResponseLabel({ last_status_code: null, last_error_code: null })).toBe("—");
  });

  it("describes each redelivery outcome", () => {
    const pending = fakeDelivery("d", "e", { status: "pending", attempt_count: 0, last_status_code: null });
    expect(redeliveryOutcome(pending)).toMatch(/queued/);
    expect(redeliveryOutcome({ ...pending, attempt_count: 1, last_error_code: "timeout" })).toBe("Attempt 1 failed (Timed out). Retrying on the normal schedule.");
    expect(redeliveryOutcome({ ...pending, status: "cancelled" })).toMatch(/cancelled/);
  });

  it("shows only the host so URL tokens stay off screen labels", () => {
    expect(hostOf("https://hooks.example.com:8443/x?token=abc")).toBe("hooks.example.com:8443");
    expect(hostOf("not a url")).toBe("not a url");
  });

  it("validates the endpoint form before calling the API", () => {
    expect(validateEndpointDraft({ url: "https://a.test/x", description: "", eventTypes: ["a"] })).toEqual({});
    expect(validateEndpointDraft({ url: "ftp://a.test", description: "", eventTypes: ["a"] }).url).toMatch(/https/);
    expect(validateEndpointDraft({ url: "a.test", description: "", eventTypes: ["a"] }).url).toMatch(/absolute URL/);
    expect(validateEndpointDraft({ url: `https://a.test/${"x".repeat(2048)}`, description: "", eventTypes: ["a"] }).url).toMatch(/2048/);
    expect(validateEndpointDraft({ url: "https://a.test", description: "x".repeat(201), eventTypes: ["a"] }).description).toMatch(/200/);
    expect(validateEndpointDraft({ url: "https://a.test", description: "a\nb", eventTypes: ["a"] }).description).toMatch(/control/);
    expect(validateEndpointDraft({ url: "https://a.test", description: "", eventTypes: Array.from({ length: 21 }, (_, i) => `t${i}`) }).event_types).toMatch(/20/);
  });
});
