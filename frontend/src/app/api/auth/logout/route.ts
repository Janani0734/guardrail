import { NextRequest, NextResponse } from "next/server";
import { REFRESH_COOKIE, backendJson, clearAuthCookies } from "@/lib/server/backend";

export async function POST(req: NextRequest) {
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value ?? null;
  await backendJson("/v1/auth/logout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  const res = NextResponse.json({ message: "Logged out" });
  clearAuthCookies(res);
  return res;
}
