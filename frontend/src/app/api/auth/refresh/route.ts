import { NextRequest, NextResponse } from "next/server";
import { REFRESH_COOKIE, authResponse, backendJson, clearAuthCookies } from "@/lib/server/backend";

export async function POST(req: NextRequest) {
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  if (!refresh) {
    return NextResponse.json({ error: { code: "NO_SESSION", message: "Not signed in" } }, { status: 401 });
  }
  const result = await backendJson("/v1/auth/refresh", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (result.status === 401) {
    const res = NextResponse.json(result.data, { status: 401 });
    clearAuthCookies(res);
    return res;
  }
  return authResponse(result);
}
