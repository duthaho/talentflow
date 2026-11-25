// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { mockActor } from "@/lib/actor/mock";

import { AppShell } from "./app-shell";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

const TENANT = "00000000-0000-4000-8000-000000000001";

function renderFor(subject: string) {
  const actor = mockActor({ subject, tenantId: TENANT, email: "demo@talentflow.local", name: "Demo User" });
  render(<AppShell actor={actor}>content</AppShell>);
  return within(screen.getByRole("navigation", { name: "Main" }));
}

describe("AppShell", () => {
  it("shows the interviewer only the sections their role allows", () => {
    const nav = renderFor("00000000-0000-4000-8000-000000000014");
    expect(nav.getAllByRole("link").map((link) => link.textContent)).toEqual(["Overview", "Interviews"]);
    expect(screen.getByText("Interviewer")).toBeInTheDocument();
    expect(screen.getByText("TalentFlow Demo")).toBeInTheDocument();
  });

  it("renders a sign-out form that posts to the logout route", () => {
    renderFor("00000000-0000-4000-8000-000000000011");
    const button = screen.getByRole("button", { name: "Sign out" });
    const form = button.closest("form");
    expect(form).toHaveAttribute("action", "/auth/logout");
    expect(form).toHaveAttribute("method", "post");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });
});
