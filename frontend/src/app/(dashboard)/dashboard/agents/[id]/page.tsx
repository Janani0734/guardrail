"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, KeyRound } from "lucide-react";
import { z } from "zod";
import { ApiKeyModal } from "@/components/forms/api-key-modal";
import { Button } from "@/components/ui/button";
import { Mono, StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/ui/modal";
import { ErrorState, Spinner, errorText, useToast } from "@/components/ui/states";
import { useActions, useAgent, useAgentTools, useAllTools, useApiKeys, useApiMutation } from "@/hooks/use-api";
import { useCan } from "@/hooks/use-role";
import { api } from "@/lib/api";
import { agentSchema, apiKeySchema, toolSchema } from "@/lib/schemas";
import { formatDateTime, formatRelative } from "@/lib/format";

export default function AgentDetail({ params }: { params: { id: string } }) {
  const { id } = params;
  const toast = useToast();
  const qc = useQueryClient();
  const canManage = useCan("MANAGER");
  const agent = useAgent(id);
  const assigned = useAgentTools(id);
  const allTools = useAllTools();
  const keys = useApiKeys({ agent_id: id, page_size: 50 });
  const actions = useActions({ agent_id: id, page_size: 8 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [keyOpen, setKeyOpen] = useState(false);
  const [revoke, setRevoke] = useState<string | null>(null);

  useEffect(() => {
    if (assigned.data) setSelected(new Set(assigned.data.map((t) => t.id)));
  }, [assigned.data]);

  const saveTools = useApiMutation((ids: string[]) => api(`/v1/agents/${id}/tools`, { method: "PUT", body: { tool_ids: ids }, schema: z.array(toolSchema) }), ["agent-tools"]);
  const toggle = useApiMutation((status: string) => api(`/v1/agents/${id}`, { method: "PATCH", body: { status }, schema: agentSchema }), ["agent", "agents"]);
  const revokeKey = useApiMutation((keyId: string) => api(`/v1/api-keys/${keyId}`, { method: "DELETE", schema: apiKeySchema }), ["api-keys"]);

  if (agent.isLoading) return <Spinner />;
  if (agent.isError || !agent.data) return <ErrorState error={agent.error} onRetry={() => agent.refetch()} />;
  const a = agent.data;
  const dirty = assigned.data ? assigned.data.length !== selected.size || assigned.data.some((t) => !selected.has(t.id)) : false;

  return (
    <>
      <Link href="/dashboard/agents" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-400 hover:text-ink-900"><ArrowLeft className="h-4 w-4" /> All agents</Link>
      <PageHeader title={a.name} description={a.description ?? undefined}
        actions={canManage ? (
          <Button variant={a.status === "ACTIVE" ? "secondary" : "primary"} loading={toggle.isPending}
            onClick={() => toggle.mutate(a.status === "ACTIVE" ? "DISABLED" : "ACTIVE", { onSuccess: () => toast.success("Agent status updated"), onError: (e) => toast.error(errorText(e)) })}>
            {a.status === "ACTIVE" ? "Disable agent" : "Enable agent"}
          </Button>) : undefined} />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm"><Mono>{a.slug}</Mono><StatusBadge value={a.status} /><span className="text-ink-400">Created {formatDateTime(a.created_at)}</span></div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Allowed tools" action={canManage ? <Button size="sm" disabled={!dirty} loading={saveTools.isPending}
            onClick={() => saveTools.mutate([...selected], { onSuccess: () => { toast.success("Tools updated"); void qc.invalidateQueries({ queryKey: ["agent-tools", id] }); }, onError: (e) => toast.error(errorText(e)) })}>Save</Button> : undefined}>
          {allTools.isLoading || assigned.isLoading ? <Spinner /> : allTools.data?.items.length === 0 ? (
            <p className="text-sm text-ink-400">No tools registered yet. <Link className="underline" href="/dashboard/tools">Register one</Link>.</p>
          ) : (
            <ul className="space-y-1.5">
              {allTools.data?.items.map((t) => (
                <li key={t.id}>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" disabled={!canManage} checked={selected.has(t.id)}
                      onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(t.id); else n.delete(t.id); return n; })} />
                    <span className="font-mono text-xs">{t.name}</span><StatusBadge value={t.risk_level} />
                  </label>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-ink-400">Tools that aren&apos;t checked here are blocked for this agent.</p>
        </Card>

        <Card title="API keys" action={canManage ? <Button size="sm" onClick={() => setKeyOpen(true)}><KeyRound className="h-3.5 w-3.5" /> Generate key</Button> : undefined}>
          <DataTable rows={keys.data?.items} rowKey={(r) => r.id} loading={keys.isLoading} error={keys.error} onRetry={() => keys.refetch()}
            empty={{ title: "No keys", description: "Generate a key so this agent can call GuardRail." }}
            columns={[
              { header: "Name", cell: (r) => <div><p className="font-medium">{r.name}</p><Mono>{r.prefix}…</Mono></div> },
              { header: "Last used", cell: (r) => (r.last_used_at ? formatRelative(r.last_used_at) : "Never") },
              { header: "Status", cell: (r) => <StatusBadge value={r.revoked_at ? "REVOKED" : "ACTIVE"} /> },
              { header: "Actions", cell: (r) => (canManage && !r.revoked_at ? <Button size="sm" variant="ghost" onClick={() => setRevoke(r.id)}>Revoke</Button> : null) },
            ]} />
        </Card>
      </div>

      <Card title="Recent actions" className="mt-4">
        <DataTable rows={actions.data?.items} rowKey={(r) => r.id} loading={actions.isLoading} error={actions.error} empty={{ title: "No actions from this agent yet" }}
          columns={[
            { header: "Tool", cell: (r) => <span className="font-mono text-xs">{r.tool}</span> },
            { header: "Env", cell: (r) => r.environment },
            { header: "Decision", cell: (r) => <StatusBadge value={r.status} /> },
            { header: "When", cell: (r) => formatDateTime(r.created_at) },
          ]} />
      </Card>

      <ApiKeyModal open={keyOpen} onClose={() => setKeyOpen(false)} agentId={id} />
      <ConfirmDialog open={!!revoke} onClose={() => setRevoke(null)} danger title="Revoke API key?" confirmLabel="Revoke key" loading={revokeKey.isPending}
        description="The agent using this key will immediately be rejected with 401. This cannot be undone."
        onConfirm={() => revoke && revokeKey.mutate(revoke, { onSuccess: () => { toast.success("Key revoked"); setRevoke(null); }, onError: (e) => toast.error(errorText(e)) })} />
    </>
  );
}
