import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh }),
  useSearchParams: () => new URLSearchParams("next=/dashboard/approvals"),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, authCall: vi.fn() };
});

import LoginPage from "@/app/(auth)/login/page";
import { ApiError, authCall } from "@/lib/api";

describe("login page", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows validation errors and does not call the API when fields are invalid", async () => {
    render(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Enter a valid email")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    expect(authCall).not.toHaveBeenCalled();
  });

  it("signs in and redirects to the requested dashboard page", async () => {
    vi.mocked(authCall).mockResolvedValue(undefined);
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "admin@guardrail.demo");
    await userEvent.type(screen.getByLabelText("Password"), "Demo@12345!");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard/approvals"));
    expect(authCall).toHaveBeenCalledWith("login", { email: "admin@guardrail.demo", password: "Demo@12345!" });
  });

  it("shows the server error when credentials are rejected", async () => {
    vi.mocked(authCall).mockRejectedValue(new ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password"));
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "admin@guardrail.demo");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(replace).not.toHaveBeenCalled();
  });
});
