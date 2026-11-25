// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NAV_ITEMS } from "@/lib/nav";

import { NavLinks } from "./nav-links";

vi.mock("next/navigation", () => ({ usePathname: () => "/candidates" }));

describe("NavLinks", () => {
  it("marks the current section for assistive technology", () => {
    render(<NavLinks items={NAV_ITEMS.slice(0, 3)} />);
    expect(screen.getByRole("link", { name: "Candidates" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });
});
