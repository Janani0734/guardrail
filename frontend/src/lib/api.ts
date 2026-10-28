import type { z } from "zod";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

let refreshing: Promise<boolean> | null = null;

/** Single-flight refresh: parallel 401s share one refresh call, so rotating refresh tokens aren't replayed. */
function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/api/auth/refresh", { method: "POST" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function endSession(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
}

interface Options<S extends z.ZodTypeAny> {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  schema?: S;
}

function buildUrl(path: string, query?: Options<z.ZodTypeAny>["query"]): string {
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return `/api/proxy${path}${qs ? `?${qs}` : ""}`;
}

async function request(path: string, opts: Options<z.ZodTypeAny>): Promise<Response> {
  const init: RequestInit = {
    method: opts.method ?? "GET",
    headers: opts.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  };
  return fetch(buildUrl(path, opts.query), init);
}

export async function api<S extends z.ZodTypeAny>(path: string, opts: Options<S> = {}): Promise<z.infer<S>> {
  let res = await request(path, opts);
  if (res.status === 401 && path !== "/v1/auth/login") {
    if (await refreshSession()) {
      res = await request(path, opts);
    }
    if (res.status === 401) {
      await endSession();
    }
  }
  if (res.status === 204) return undefined as z.infer<S>;
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    throw new ApiError(res.status, "BAD_RESPONSE", "The server returned an unreadable response");
  }
  if (!res.ok) {
    const err = (json as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
    throw new ApiError(res.status, err?.code ?? "REQUEST_FAILED", err?.message ?? `Request failed (${res.status})`, err?.details);
  }
  return opts.schema ? (opts.schema.parse(json) as z.infer<S>) : (json as z.infer<S>);
}

/** Auth calls go to dedicated route handlers that manage the httpOnly cookies. */
export async function authCall(kind: "login" | "register", body: unknown): Promise<void> {
  const res = await fetch(`/api/auth/${kind}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    const json = (await res.json().catch(() => null)) as { error?: { code?: string; message?: string; details?: unknown } } | null;
    throw new ApiError(res.status, json?.error?.code ?? "REQUEST_FAILED", json?.error?.message ?? "Request failed", json?.error?.details);
  }
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
}
