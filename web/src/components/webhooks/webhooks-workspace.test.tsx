// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PROBLEM_TYPE_BASE } from "@/lib/api/problem";

import { fakeDelivery, fakeEndpoint, fakeWebhooksBackend } from "../../../test/webhooks-fake";
import { WebhooksWorkspace } from "./webhooks-workspace";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
const router = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const LIVE = { enabled: true, deliveryPaused: false };
const GATE_OFF = { enabled: false, deliveryPaused: false };
const DISABLED_NOTICE = /Webhooks are turned off for your organization\. You can still view, disable, rotate or delete existing endpoints\./;

type Backend = ReturnType<typeof fakeWebhooksBackend>;

async function settled() {
  await waitFor(() => expect(document.querySelectorAll('[aria-busy="true"]')).toHaveLength(0));
}

async function renderWorkspace(backend: Backend, feature = LIVE) {
  const view = render(<WebhooksWorkspace feature={feature} api={backend.api} pollIntervalMs={1} pollTimeoutMs={200} />);
  await settled();
  return view;
}

function endpointRow(host: string) {
  return screen.getByRole("listitem", { name: host });
}

function writes(backend: Backend) {
  return backend.requests.filter((request) => request.method !== "GET");
}

async function typeInto(field: HTMLElement, text: string) {
  await userEvent.clear(field);
  await userEvent.click(field);
  await userEvent.paste(text);
}

beforeEach(() => {
  router.refresh.mockClear();
  vi.mocked(toast.error).mockClear();
  vi.mocked(toast.success).mockClear();
});

describe("WebhooksWorkspace endpoints (AC1)", () => {
  it("lists endpoints with status, subscriptions and why a disabled one stopped", async () => {
    const backend = fakeWebhooksBackend({
      endpoints: [
        fakeEndpoint("crm", { description: "CRM sync", event_types: ["candidate_case.created.v1", "candidate_case.stage_changed.v1"] }),
        fakeEndpoint("old", { status: "disabled", disabled_reason: "failing" }),
      ],
    });
    await renderWorkspace(backend);

    const crm = endpointRow("crm.example.com");
    expect(within(crm).getByText("CRM sync")).toBeInTheDocument();
    expect(within(crm).getByText("Enabled")).toBeInTheDocument();
    expect(within(within(crm).getByRole("list", { name: "Subscribed events" })).getAllByRole("listitem")).toHaveLength(2);
    const old = endpointRow("old.example.com");
    expect(within(old).getByText("Disabled after repeated failures")).toBeInTheDocument();
    expect(within(old).getByRole("button", { name: "Enable old.example.com" })).toBeInTheDocument();
    expect(screen.queryByText(/whsec_/)).not.toBeInTheDocument();
  });

  it("shows an empty state, and a retryable error when the API refuses", async () => {
    let calls = 0;
    const backend = fakeWebhooksBackend({
      override: (request) =>
        request.method === "GET" && new URL(request.url).pathname === "/v1/webhook-endpoints" && calls++ === 0
          ? Response.json({ type: `${PROBLEM_TYPE_BASE}forbidden`, title: "Forbidden", status: 403, detail: "Missing permission webhook:manage" }, { status: 403 })
          : undefined,
    });
    await renderWorkspace(backend);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("You don't have access");
    expect(alert).toHaveTextContent("Missing permission webhook:manage");
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await settled();
    expect(screen.getByText(/No webhook endpoints yet/)).toBeInTheDocument();
  });

  it("creates an endpoint and shows its signing secret exactly once", async () => {
    const backend = fakeWebhooksBackend();
    await renderWorkspace(backend);

    await userEvent.click(screen.getByRole("button", { name: "New endpoint" }));
    let dialog = screen.getByRole("dialog", { name: "New webhook endpoint" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Create endpoint" }));
    expect(within(dialog).getByText("Enter the receiver URL.")).toBeInTheDocument();
    expect(within(dialog).getByText("Pick at least one event.")).toBeInTheDocument();
    expect(writes(backend)).toHaveLength(0);

    await typeInto(within(dialog).getByLabelText("Receiver URL"), "https://hooks.acme.test/tf");
    await typeInto(within(dialog).getByLabelText("Description (optional)"), "Acme HRIS");
    await userEvent.click(within(dialog).getByLabelText(/candidate_case\.stage_changed\.v1/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create endpoint" }));

    dialog = await screen.findByRole("dialog", { name: "Endpoint created" });
    expect(within(dialog).getByText("This is the only time the secret is shown")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Signing secret")).toHaveValue("whsec_created_new-1");
    const [post] = writes(backend);
    expect(await post.json()).toEqual({ url: "https://hooks.acme.test/tf", description: "Acme HRIS", event_types: ["candidate_case.stage_changed.v1"], enabled: true });

    await userEvent.click(within(dialog).getByRole("button", { name: "I've stored the secret" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByDisplayValue(/whsec_/)).not.toBeInTheDocument();
    expect(endpointRow("hooks.acme.test")).toHaveTextContent("Acme HRIS");
  });

  it("puts the API's URL rejection on the URL field", async () => {
    const backend = fakeWebhooksBackend();
    await renderWorkspace(backend);
    await userEvent.click(screen.getByRole("button", { name: "New endpoint" }));
    const dialog = screen.getByRole("dialog", { name: "New webhook endpoint" });
    await typeInto(within(dialog).getByLabelText("Receiver URL"), "http://hooks.acme.test/tf");
    await userEvent.click(within(dialog).getByLabelText(/candidate_case\.created\.v1/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create endpoint" }));

    expect(await within(dialog).findByText("The URL must use https.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Receiver URL")).toHaveAttribute("aria-invalid", "true");
  });

  it("edits subscriptions with the endpoint version as If-Match", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm", { version: 3 })] });
    await renderWorkspace(backend);

    await userEvent.click(screen.getByRole("button", { name: "Edit crm.example.com" }));
    const dialog = screen.getByRole("dialog", { name: "Edit webhook endpoint" });
    expect(within(dialog).getByLabelText(/candidate_case\.created\.v1/)).toBeChecked();
    await userEvent.click(within(dialog).getByLabelText(/offer\.created\.v1/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [patch] = writes(backend);
    expect(patch.method).toBe("PATCH");
    expect(patch.headers.get("if-match")).toBe('"3"');
    expect((await patch.json()).event_types).toEqual(["candidate_case.created.v1", "offer.created.v1"]);
    expect(within(within(endpointRow("crm.example.com")).getByRole("list", { name: "Subscribed events" })).getAllByRole("listitem")).toHaveLength(2);
  });

  it("reloads the list when someone else changed the endpoint first", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")] });
    await renderWorkspace(backend);
    backend.store.get("crm")!.version = 2;
    backend.store.get("crm")!.description = "Changed elsewhere";

    await userEvent.click(screen.getByRole("button", { name: "Edit crm.example.com" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Someone else changed this", expect.anything()));
    await settled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(endpointRow("crm.example.com")).toHaveTextContent("Changed elsewhere");
  });

  it("disables and re-enables an endpoint", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")] });
    await renderWorkspace(backend);

    await userEvent.click(screen.getByRole("button", { name: "Disable crm.example.com" }));
    await waitFor(() => expect(endpointRow("crm.example.com")).toHaveTextContent("Disabled by an admin"));
    await userEvent.click(screen.getByRole("button", { name: "Enable crm.example.com" }));
    await waitFor(() => expect(within(endpointRow("crm.example.com")).getByText("Enabled")).toBeInTheDocument());

    const [disable, enable] = writes(backend);
    expect(await disable.json()).toEqual({ enabled: false });
    expect(disable.headers.get("if-match")).toBe('"1"');
    expect(enable.headers.get("if-match")).toBe('"2"');
  });

  it("rotates the secret and shows the new one once, with the grace period chosen", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")] });
    await renderWorkspace(backend);

    await userEvent.click(screen.getByRole("button", { name: "Rotate secret for crm.example.com" }));
    let dialog = screen.getByRole("dialog", { name: "Rotate signing secret" });
    expect(within(dialog).getByLabelText("24 hours (recommended)")).toBeChecked();
    await userEvent.click(within(dialog).getByRole("button", { name: "Rotate secret" }));

    dialog = await screen.findByRole("dialog", { name: "New signing secret" });
    expect(within(dialog).getByLabelText("Signing secret")).toHaveValue("whsec_rotated_crm-s2");
    expect(dialog).toHaveTextContent("The previous secret keeps signing until Nov 28, 2026");
    const [rotation] = writes(backend);
    expect(rotation.headers.get("if-match")).toBe('"1"');
    expect(await rotation.json()).toEqual({ grace_period_seconds: 86400 });

    await userEvent.click(within(dialog).getByRole("button", { name: "I've stored the secret" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(endpointRow("crm.example.com")).toHaveTextContent("previous secret expires Nov 28, 2026");
  });

  it("deletes an endpoint after confirmation", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")] });
    await renderWorkspace(backend);

    await userEvent.click(screen.getByRole("button", { name: "Delete crm.example.com" }));
    await userEvent.click(within(screen.getByRole("dialog", { name: "Delete endpoint?" })).getByRole("button", { name: "Delete endpoint" }));

    await waitFor(() => expect(screen.queryByRole("listitem", { name: "crm.example.com" })).not.toBeInTheDocument());
    expect(writes(backend)[0].method).toBe("DELETE");
    expect(writes(backend)[0].headers.get("if-match")).toBe('"1"');
  });
});

describe("WebhooksWorkspace delivery log (AC2)", () => {
  const deliveries = [
    fakeDelivery("ok", "crm", { created_at: "2026-11-21T10:00:00Z" }),
    fakeDelivery("dead", "crm", {
      status: "dead_lettered",
      attempt_count: 8,
      last_status_code: 503,
      created_at: "2026-11-22T10:00:00Z",
      last_attempt_at: "2026-11-23T10:00:00Z",
      completed_at: "2026-11-23T10:00:00Z",
    }),
    fakeDelivery("wait", "crm", { status: "pending", attempt_count: 2, last_status_code: null, last_error_code: "timeout", completed_at: null, created_at: "2026-11-24T10:00:00Z" }),
  ];

  async function openLog(backend: Backend) {
    await renderWorkspace(backend);
    await userEvent.click(screen.getByRole("button", { name: "Deliveries for crm.example.com" }));
    await settled();
    return screen.getByRole("region", { name: "Delivery log: crm.example.com" });
  }

  function row(id: string) {
    return document.querySelector<HTMLElement>(`tr[data-delivery-id="${id}"]`)!;
  }

  it("shows status, attempts, last response and timestamps for each delivery", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")], deliveries });
    const log = await openLog(backend);

    expect(within(log).getAllByRole("row")).toHaveLength(4);
    const dead = row("dead");
    expect(dead).toHaveTextContent("Dead-lettered");
    expect(dead).toHaveTextContent("8 / 8");
    expect(dead).toHaveTextContent("HTTP 503");
    expect(dead).toHaveTextContent("Nov 22, 2026");
    expect(dead).toHaveTextContent("Nov 23, 2026");
    expect(row("wait")).toHaveTextContent("Timed out");
    expect(within(row("wait")).queryByRole("button")).not.toBeInTheDocument();
  });

  it("filters to dead-lettered deliveries", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")], deliveries });
    const log = await openLog(backend);

    await userEvent.selectOptions(within(log).getByLabelText("Status"), "dead_lettered");
    await settled();

    expect(within(log).getAllByRole("row")).toHaveLength(2);
    expect(row("dead")).toBeInTheDocument();
    const lastList = backend.requests.filter((request) => request.url.includes("/deliveries")).at(-1)!;
    expect(new URL(lastList.url).searchParams.getAll("status")).toEqual(["dead_lettered"]);

    await userEvent.selectOptions(within(log).getByLabelText("Status"), "cancelled");
    await settled();
    expect(within(log).getByText("No cancelled deliveries.")).toBeInTheDocument();
  });

  it("redelivers a dead-lettered delivery and shows the result", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")], deliveries });
    await openLog(backend);

    await userEvent.click(within(row("dead")).getByRole("button", { name: /^Redeliver candidate_case\.created\.v1 dead-eve/ }));

    await waitFor(() => expect(screen.getByText(/Redelivery succeeded \(HTTP 204\)\./)).toBeInTheDocument());
    const post = backend.requests.find((request) => request.method === "POST")!;
    expect(new URL(post.url).pathname).toBe("/v1/webhook-deliveries/dead/redeliveries");
    expect(post.headers.get("idempotency-key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(backend.requests.some((request) => request.url.endsWith("/v1/webhook-deliveries/re-1"))).toBe(true);

    await userEvent.click(screen.getByRole("button", { name: "Disable crm.example.com" }));
    await waitFor(() => expect(endpointRow("crm.example.com")).toHaveTextContent("Disabled by an admin"));
    expect(writes(backend).at(-1)!.headers.get("if-match")).toBe('"2"');
  });

  it("reports a failed redelivery attempt", async () => {
    const backend = fakeWebhooksBackend({
      endpoints: [fakeEndpoint("crm")],
      deliveries,
      redeliveryResult: (pending) => ({ ...pending, status: "dead_lettered", attempt_count: 8, last_status_code: 500, completed_at: "2026-11-27T12:00:00Z" }),
    });
    await openLog(backend);
    await userEvent.click(within(row("ok")).getByRole("button", { name: /^Redeliver/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Redelivery failed after 8 attempts (HTTP 500).");
  });

  it("shows why the API refused a redelivery", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")], deliveries });
    await openLog(backend);
    backend.store.get("crm")!.status = "disabled";

    await userEvent.click(within(row("dead")).getByRole("button", { name: /^Redeliver/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("the endpoint is disabled");
  });

  it("offers no redelivery while the endpoint is disabled", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm", { status: "disabled", disabled_reason: "manual" })], deliveries });
    const log = await openLog(backend);

    expect(within(log).getByText("Enable this endpoint to redeliver events to it.")).toBeInTheDocument();
    expect(within(log).queryByRole("button", { name: /^Redeliver/ })).not.toBeInTheDocument();
  });

  it("shows an empty log and a retryable load error", async () => {
    let failures = 1;
    const backend = fakeWebhooksBackend({
      endpoints: [fakeEndpoint("crm")],
      override: (request) =>
        request.url.includes("/deliveries") && failures-- > 0 ? Response.json({ type: "about:blank", title: "Boom", status: 500, detail: "x" }, { status: 500 }) : undefined,
    });
    const log = await openLog(backend);

    await userEvent.click(within(within(log).getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settled();
    expect(within(log).getByText(/No deliveries yet/)).toBeInTheDocument();
  });
});

describe("WebhooksWorkspace feature gate (ADR-010 §4)", () => {
  const dead = fakeDelivery("dead", "crm", { status: "dead_lettered", attempt_count: 8, last_status_code: 503, completed_at: "2026-11-23T10:00:00Z" });

  function actions(host: string) {
    return within(endpointRow(host))
      .getAllByRole("button")
      .map((button) => button.textContent);
  }

  it("keeps existing endpoints reachable but read-only while the gate is off", async () => {
    const backend = fakeWebhooksBackend({
      webhooksEnabled: false,
      endpoints: [fakeEndpoint("crm"), fakeEndpoint("old", { status: "disabled", disabled_reason: "manual" })],
      deliveries: [dead],
    });
    await renderWorkspace(backend, GATE_OFF);

    expect(screen.getByRole("status")).toHaveTextContent(DISABLED_NOTICE);
    expect(screen.getByRole("status")).toHaveTextContent("Events for enabled endpoints are kept and sent if webhooks are turned back on.");
    expect(screen.queryByRole("button", { name: "New endpoint" })).not.toBeInTheDocument();
    expect(actions("crm.example.com")).toEqual(["Deliveries", "Disable", "Rotate secret", "Delete"]);
    expect(actions("old.example.com")).toEqual(["Deliveries", "Rotate secret", "Delete"]);

    await userEvent.click(screen.getByRole("button", { name: "Deliveries for crm.example.com" }));
    await settled();
    const log = screen.getByRole("region", { name: "Delivery log: crm.example.com" });
    expect(log.querySelector(`tr[data-delivery-id="dead"]`)).toHaveTextContent("Dead-lettered");
    expect(within(log).queryByRole("button", { name: /^Redeliver/ })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Disable crm.example.com" }));
    await waitFor(() => expect(endpointRow("crm.example.com")).toHaveTextContent("Disabled by an admin"));
    expect(await writes(backend)[0].json()).toEqual({ enabled: false });
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("says webhooks are not available yet when the gate is off and nothing exists", async () => {
    await renderWorkspace(fakeWebhooksBackend({ webhooksEnabled: false }), GATE_OFF);
    expect(screen.getByText("Webhooks are not available for your organization yet.")).toBeInTheDocument();
    expect(screen.queryByText(/No webhook endpoints yet/)).not.toBeInTheDocument();
  });

  it("warns that delivery is paused without restricting management", async () => {
    await renderWorkspace(fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm")] }), { enabled: true, deliveryPaused: true });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Delivery is paused for your organization. Pending deliveries are kept and will be sent when delivery resumes; waiting does not use up retry attempts.",
    );
    expect(screen.getByRole("button", { name: "New endpoint" })).toBeEnabled();
    expect(actions("crm.example.com")).toEqual(["Deliveries", "Edit", "Disable", "Rotate secret", "Delete"]);
  });

  it("shows only the disabled notice during a flagd outage, whose fallback is gate off and delivery paused", async () => {
    await renderWorkspace(fakeWebhooksBackend({ webhooksEnabled: false, endpoints: [fakeEndpoint("crm")] }), { enabled: false, deliveryPaused: true });
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent(DISABLED_NOTICE);
    expect(screen.queryByText(/Delivery is paused/)).not.toBeInTheDocument();
  });

  it("switches to the disabled notice and refreshes the server render when create hits a closed gate", async () => {
    const backend = fakeWebhooksBackend();
    await renderWorkspace(backend);
    backend.gate.enabled = false;

    await userEvent.click(screen.getByRole("button", { name: "New endpoint" }));
    const dialog = screen.getByRole("dialog", { name: "New webhook endpoint" });
    await typeInto(within(dialog).getByLabelText("Receiver URL"), "https://hooks.acme.test/tf");
    await userEvent.click(within(dialog).getByLabelText(/candidate_case\.created\.v1/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create endpoint" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent(DISABLED_NOTICE);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New endpoint" })).not.toBeInTheDocument();
    expect(router.refresh).toHaveBeenCalledOnce();
  });

  it("handles a closed gate on edit, re-enable and redeliver the same way", async () => {
    const backend = fakeWebhooksBackend({ endpoints: [fakeEndpoint("crm"), fakeEndpoint("old", { status: "disabled", disabled_reason: "manual" })], deliveries: [dead] });

    const first = await renderWorkspace(backend);
    backend.gate.enabled = false;
    await userEvent.click(screen.getByRole("button", { name: "Edit crm.example.com" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(DISABLED_NOTICE));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    first.unmount();

    backend.gate.enabled = true;
    const second = await renderWorkspace(backend);
    backend.gate.enabled = false;
    await userEvent.click(screen.getByRole("button", { name: "Enable old.example.com" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(DISABLED_NOTICE));
    expect(toast.error).not.toHaveBeenCalled();
    second.unmount();

    backend.gate.enabled = true;
    await renderWorkspace(backend);
    await userEvent.click(screen.getByRole("button", { name: "Deliveries for crm.example.com" }));
    await settled();
    backend.gate.enabled = false;
    await userEvent.click(screen.getByRole("button", { name: /^Redeliver/ }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(DISABLED_NOTICE));
    expect(screen.queryByRole("button", { name: /^Redeliver/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    expect(router.refresh).toHaveBeenCalledTimes(3);
  });

  it("restores the full workspace when a refreshed render reports the gate on again", async () => {
    const backend = fakeWebhooksBackend({ webhooksEnabled: false, endpoints: [fakeEndpoint("crm")] });
    const view = await renderWorkspace(backend, GATE_OFF);
    expect(screen.queryByRole("button", { name: "New endpoint" })).not.toBeInTheDocument();

    backend.gate.enabled = true;
    view.rerender(<WebhooksWorkspace feature={LIVE} api={backend.api} pollIntervalMs={1} pollTimeoutMs={200} />);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New endpoint" })).toBeInTheDocument();
    expect(actions("crm.example.com")).toContain("Edit");
  });
});
