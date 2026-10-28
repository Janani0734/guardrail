import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, backendUrl } from "@/lib/server/backend";

/**
 * Same-origin proxy to the FastAPI backend. It attaches the access token from the httpOnly cookie, so the JWT is
 * never readable by browser JavaScript (XSS cannot exfiltrate it) and the backend needs no CORS for the dashboard.
 * Only /v1/** is forwarded; agent-facing endpoints authenticate with X-API-Key and are not meant to go through here.
 */
async function forward(req: NextRequest, { params }: { params: { path: string[] } }) {
  const path = params.path.join("/");
  if (!path.startsWith("v1/") || path.includes("..")) {
    return NextResponse.json({ error: { code: "NOT_FOUND", message: "Unknown API path" } }, { status: 404 });
  }
  const headers = new Headers();
  const token = req.cookies.get(ACCESS_COOKIE)?.value;
  if (token) headers.set("authorization", `Bearer ${token}`);
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);

  const hasBody = !["GET", "HEAD"].includes(req.method);
  try {
    const upstream = await fetch(`${backendUrl()}/${path}${req.nextUrl.search}`, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
    });
    const out = new NextResponse(upstream.status === 204 ? null : await upstream.arrayBuffer(), { status: upstream.status });
    const upstreamType = upstream.headers.get("content-type");
    if (upstreamType) out.headers.set("content-type", upstreamType);
    return out;
  } catch {
    return NextResponse.json({ error: { code: "BACKEND_UNREACHABLE", message: "Cannot reach the GuardRail API" } }, { status: 502 });
  }
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
