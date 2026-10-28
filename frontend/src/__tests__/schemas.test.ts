import { describe, expect, it } from "vitest";
import { approvalSchema, decisionSchema, loginSchema } from "@/lib/schemas";

describe("API schemas", () => {
  it("accepts the three gateway decisions and rejects anything else", () => {
    for (const d of ["ALLOW", "BLOCK", "REQUIRE_APPROVAL"]) expect(decisionSchema.safeParse(d).success).toBe(true);
    expect(decisionSchema.safeParse("MAYBE").success).toBe(false);
  });

  it("coerces estimated_cost from a string to a number", () => {
    const parsed = approvalSchema.parse({
      id: "a1", action_request_id: "r1", action_id: "act_1", agent_slug: "support-agent-01", tool: "send_email",
      environment: "production", estimated_cost: "15.00", arguments: { to: "x@example.com" }, reason: null,
      message: null, status: "PENDING", expires_at: "2026-10-28T10:30:00Z", created_at: "2026-10-28T10:00:00Z",
    });
    expect(parsed.estimated_cost).toBe(15);
  });

  it("validates the login form fields", () => {
    expect(loginSchema.safeParse({ email: "bad", password: "x" }).success).toBe(false);
    expect(loginSchema.safeParse({ email: "admin@guardrail.demo", password: "" }).success).toBe(false);
    expect(loginSchema.safeParse({ email: "admin@guardrail.demo", password: "secret" }).success).toBe(true);
  });
});
