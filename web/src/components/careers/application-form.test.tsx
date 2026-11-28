// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { ApplicationForm } from "./application-form";

describe("anonymous application form", () => {
  it("renders the server text safely and keeps the honeypot accessible but out of tab order", () => {
    const text = "<img src=x onerror=alert(1)> exact server consent";
    const { container } = render(
      <ApplicationForm
        slug="demo"
        requisitionId="job"
        consent={{ version: "careers-v1", text }}
        policy={{ max_bytes: 5242880, content_types: ["application/pdf"] }}
      />,
    );
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    const trap = screen.getByLabelText("Leave this field empty");
    expect(trap).toHaveAttribute("tabindex", "-1");
    expect(trap).toHaveAttribute("autocomplete", "off");
    expect(trap.closest(".sr-only")).not.toBeNull();
    expect(screen.getByRole("checkbox")).toBeRequired();
  });
});

it.each([
  [413, "Your application is too large"],
  [422, "Check your details and CV"],
  [429, "Too many applications"],
  [503, "Applications are temporarily unavailable"],
])("shows a specific message for status %s", async (status, message) => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(new Response("", { status: Number(status) })),
      ),
  );
  try {
    const user = userEvent.setup();
    render(
      <ApplicationForm
        slug="demo"
        requisitionId="job"
        consent={{ version: "careers-v1", text: "Exact consent" }}
        policy={{ max_bytes: 5242880, content_types: ["application/pdf"] }}
      />,
    );
    await user.type(screen.getByLabelText("First name"), "Demo");
    await user.type(screen.getByLabelText("Last name"), "Candidate");
    await user.type(screen.getByLabelText("Email"), "demo@example.test");
    await user.upload(
      screen.getByLabelText(/CV \(PDF/),
      new File(["%PDF-1.7"], "resume.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("checkbox"));
    // jsdom's native form serialization does not see userEvent's uploaded FileList.
    // Supply the valid browser submission at this boundary; Playwright covers serialization.
    const submitted = new FormData();
    submitted.set("cv", new File(["%PDF-1.7"], "resume.pdf", { type: "application/pdf" }));
    expect(submitted.get("cv")).toBeInstanceOf(File);
    vi.stubGlobal("FormData", vi.fn(function () { return submitted; }));
    fireEvent.submit(screen.getByRole("button", { name: "Send application" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(String(message));
  } finally {
    vi.unstubAllGlobals();
  }
});
