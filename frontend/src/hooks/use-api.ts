"use client";

import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "@/lib/api";
import * as s from "@/lib/schemas";

type Query = Record<string, string | number | boolean | undefined | null>;

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api("/v1/auth/me", { schema: s.meSchema }), staleTime: 60_000, retry: false });
}

function usePage<T extends z.ZodTypeAny>(key: string, path: string, item: T, query: Query, refetchInterval?: number) {
  return useQuery({
    queryKey: [key, query],
    queryFn: () => api(path, { query, schema: s.pageOf(item) }),
    placeholderData: keepPreviousData,
    refetchInterval,
  });
}

export const useAgents = (q: Query) => usePage("agents", "/v1/agents", s.agentSchema, q);
export const useTools = (q: Query) => usePage("tools", "/v1/tools", s.toolSchema, q);
export const useApiKeys = (q: Query) => usePage("api-keys", "/v1/api-keys", s.apiKeyListItemSchema, q);
export const usePolicies = (q: Query) => usePage("policies", "/v1/policies", s.policySchema, q);
export const useApprovals = (q: Query) => usePage("approvals", "/v1/approvals", s.approvalSchema, q, 10_000);
export const useActions = (q: Query) => usePage("actions", "/v1/action-history", s.actionSchema, q, 15_000);
export const useAuditLogs = (q: Query) => usePage("audit-logs", "/v1/audit-logs", s.auditSchema, q);

export function useAgent(id: string) {
  return useQuery({ queryKey: ["agent", id], queryFn: () => api(`/v1/agents/${id}`, { schema: s.agentSchema }) });
}
export function useAgentTools(id: string) {
  return useQuery({ queryKey: ["agent-tools", id], queryFn: () => api(`/v1/agents/${id}/tools`, { schema: z.array(s.toolSchema) }) });
}
export function useAllTools() {
  return useQuery({ queryKey: ["tools-all"], queryFn: () => api("/v1/tools", { query: { page_size: 200 }, schema: s.pageOf(s.toolSchema) }) });
}
export function useActionDetail(id: string | null) {
  return useQuery({ queryKey: ["action", id], enabled: !!id, queryFn: () => api(`/v1/action-history/${id}`, { schema: s.actionDetailSchema }) });
}
export function useAnalytics(days: number) {
  return useQuery({ queryKey: ["analytics", days], queryFn: () => api("/v1/analytics", { query: { days }, schema: s.analyticsSchema }), refetchInterval: 30_000 });
}
export function useMembers() {
  return useQuery({ queryKey: ["members"], queryFn: () => api("/v1/members", { schema: z.array(s.memberSchema) }) });
}
export function useAuditVerify(enabled: boolean) {
  return useQuery({ queryKey: ["audit-verify"], enabled, queryFn: () => api("/v1/audit-logs/verify", { schema: s.auditVerifySchema }) });
}

/** Mutation that invalidates the given query keys on success. */
export function useApiMutation<TVars, TOut = unknown>(fn: (vars: TVars) => Promise<TOut>, invalidate: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(invalidate.map((k) => qc.invalidateQueries({ queryKey: [k] }))),
  });
}
