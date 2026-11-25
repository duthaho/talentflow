// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Actor, Role } from "@/lib/actor/actor";

import { ROLE_PERMISSIONS } from "../../../test/role-permissions";

import { AppShell } from "./app-shell";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

function renderFor(role: Role, email: string | null = "demo@talentflow.local") {
  const actor: Actor = {
    userId: "u-1",
    email,
    displayName: "Demo User",
    tenantId: "t-1",
    tenantName: "TalentFlow Demo",
    role,
    permissions: ROLE_PERMISSIONS[role],
  };
  render(<AppShell actor={actor}>content</AppShell>);
  return within(screen.getByRole("navigation", { name: "Main" }));
}

describe("AppShell", () => {
  it("shows the interviewer only the sections their role allows", () => {
    const nav = renderFor("interviewer");
    expect(nav.getAllByRole("link").map((link) => link.textContent)).toEqual(["Overview", "Interviews"]);
    expect(screen.getByText("Interviewer")).toBeInTheDocument();
    expect(screen.getByText("TalentFlow Demo")).toBeInTheDocument();
  });

  it("renders a sign-out form that posts to the logout route", () => {
    renderFor("tenant_admin");
    const button = screen.getByRole("button", { name: "Sign out" });
    const form = button.closest("form");
    expect(form).toHaveAttribute("action", "/auth/logout");
    expect(form).toHaveAttribute("method", "post");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });

  it("omits the email line when the API has no email for the user", () => {
    renderFor("recruiter", null);
    expect(screen.queryByText("demo@talentflow.local")).not.toBeInTheDocument();
    expect(screen.getByText("Demo User")).toBeInTheDocument();
  });
});
