import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "@/components/ui/badge";

describe("StatusBadge", () => {
  it("renders an ALLOW decision with the green style", () => {
    render(<StatusBadge value="ALLOW" />);
    expect(screen.getByText("ALLOW").className).toContain("bg-allow-bg");
  });

  it("renders a BLOCK decision with the red style", () => {
    render(<StatusBadge value="BLOCK" />);
    expect(screen.getByText("BLOCK").className).toContain("bg-block-bg");
  });

  it("replaces underscores so REQUIRE_APPROVAL reads naturally", () => {
    render(<StatusBadge value="REQUIRE_APPROVAL" />);
    const badge = screen.getByText("REQUIRE APPROVAL");
    expect(badge.className).toContain("bg-review-bg");
  });

  it("falls back to the neutral style for unknown values", () => {
    render(<StatusBadge value="SOMETHING_NEW" />);
    expect(screen.getByText("SOMETHING NEW").className).toContain("bg-expired-bg");
  });
});
