import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { ApiError } from "@/lib/api";

describe("empty and error states", () => {
  it("shows the empty-state title and description", () => {
    render(<EmptyState title="No policies yet" description="Add a policy to start." />);
    expect(screen.getByText("No policies yet")).toBeInTheDocument();
    expect(screen.getByText("Add a policy to start.")).toBeInTheDocument();
  });

  it("shows a generic message for unknown errors and retries on click", async () => {
    const retry = vi.fn();
    render(<ErrorState error={new Error("boom")} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("shows the API error message when the backend sent one", () => {
    render(<ErrorState error={new ApiError(503, "STATE_STORE_UNAVAILABLE", "State store unavailable")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("State store unavailable");
  });
});
