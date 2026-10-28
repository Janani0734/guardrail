import { NextResponse, type NextRequest } from "next/server";

/** Cheap gate: no session cookies -> login. Real authorisation always happens in the API on every request. */
export function middleware(req: NextRequest) {
  const hasSession = req.cookies.has("gr_access") || req.cookies.has("gr_refresh");
  if (!hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(req.nextUrl.pathname)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/dashboard/:path*"] };
