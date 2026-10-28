"use client";

import { useMe } from "@/hooks/use-api";
import type { Role } from "@/types";

const RANK: Record<Role, number> = { VIEWER: 1, MANAGER: 2, ADMIN: 3 };

/** UI affordance only — the API enforces roles on every request. */
export function useCan(minimum: Role): boolean {
  const me = useMe();
  return !!me.data && RANK[me.data.role] >= RANK[minimum];
}
