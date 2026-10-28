import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Landing from "@/app/page";

describe("landing page", () => {
  it("explains the product and shows all three decision types", () => {
    render(<Landing />);
    expect(screen.getByText(/Your agent asks first/i)).toBeInTheDocument();
    expect(screen.getByText("ALLOW")).toBeInTheDocument();
    expect(screen.getByText("BLOCK")).toBeInTheDocument();
    expect(screen.getByText("REQUIRE APPROVAL")).toBeInTheDocument();
  });

  it("links to sign in and to creating a workspace", () => {
    render(<Landing />);
    expect(screen.getAllByRole("link", { name: /sign in/i })[0]).toHaveAttribute("href", "/login");
    expect(screen.getAllByRole("link", { name: /create/i })[0]).toHaveAttribute("href", "/register");
  });
});
