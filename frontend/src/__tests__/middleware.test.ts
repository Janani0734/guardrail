// @vitest-environment node
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { middleware } from "@/middleware";

const req = (path: string, cookie?: string) =>
  new NextRequest(`http://localhost:3000${path}`, cookie ? { headers: { cookie } } : undefined);

describe("dashboard middleware", () => {
  it("redirects visitors without a session cookie to /login and remembers the page", () => {
    const res = middleware(req("/dashboard/approvals"));
    expect(res.status).toBe(307);
    const location = new URL(res.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/dashboard/approvals");
  });

  it("lets a request with an access cookie through", () => {
    const res = middleware(req("/dashboard", "gr_access=abc"));
    expect(res.headers.get("location")).toBeNull();
  });

  it("lets a request with only a refresh cookie through so the API can refresh it", () => {
    const res = middleware(req("/dashboard", "gr_refresh=abc"));
    expect(res.headers.get("location")).toBeNull();
  });
});
