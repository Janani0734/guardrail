import { NextResponse } from "next/server";

export const ACCESS_COOKIE = "gr_access";
export const REFRESH_COOKIE = "gr_refresh";

export function backendUrl(): string {
  const url = process.env.BACKEND_URL;
  if (!url) throw new Error("BACKEND_URL is not set (see frontend/.env.example)");
  return url.replace(/\/+$/, "");
}

export interface TokenBundle {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

const base = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

export function setAuthCookies(res: NextResponse, tokens: TokenBundle): void {
  res.cookies.set(ACCESS_COOKIE, tokens.access_token, { ...base, maxAge: tokens.expires_in });
  res.cookies.set(REFRESH_COOKIE, tokens.refresh_token, { ...base, maxAge: 60 * 60 * 24 * 7 });
}

export function clearAuthCookies(res: NextResponse): void {
  res.cookies.set(ACCESS_COOKIE, "", { ...base, maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { ...base, maxAge: 0 });
}

export async function backendJson(path: string, init: RequestInit): Promise<{ status: number; data: unknown }> {
  try {
    const res = await fetch(`${backendUrl()}${path}`, { ...init, cache: "no-store" });
    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { error: { code: "BAD_GATEWAY", message: "Backend returned a non-JSON response" } };
    }
    return { status: res.status, data };
  } catch {
    return { status: 502, data: { error: { code: "BACKEND_UNREACHABLE", message: "Cannot reach the GuardRail API" } } };
  }
}

interface AuthPayload {
  tokens: TokenBundle;
  user: unknown;
  organization: unknown;
  role: unknown;
}

/** Forwards a login/register/refresh result to the browser: tokens go into httpOnly cookies, never into JS. */
export function authResponse(result: { status: number; data: unknown }, okStatus = 200): NextResponse {
  if (result.status >= 400 || !result.data) {
    return NextResponse.json(result.data ?? { error: { code: "UNKNOWN", message: "Request failed" } }, { status: result.status || 500 });
  }
  const { tokens, user, organization, role } = result.data as AuthPayload;
  const res = NextResponse.json({ user, organization, role }, { status: okStatus });
  setAuthCookies(res, tokens);
  return res;
}
