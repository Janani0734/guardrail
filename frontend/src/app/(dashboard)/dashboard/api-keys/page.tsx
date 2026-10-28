"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";
import { ApiKeyModal } from "@/components/forms/api-key-modal";
import { Button } from "@/components/ui/button";
import { Mono, StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable, FilterBar } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/ui/modal";
import { errorText, useToast } from "@/components/ui/states";
import { useApiKeys, useApiMutation } from "@/hooks/use-api";
import { useCan } from "@/hooks/use-role";
import { api } from "@/lib/api";
import { apiKeySchema } from "@/lib/schemas";
import { formatDateTime, formatRelative } from "@/lib/format";

export default function ApiKeysPage() {
  const toast = useToast();
  const canManage = useCan("MANAGER");
  const [page, setPage] = useState(1);
  const [activeOnly, setActiveOnly] = useState(false);
  const [open, setOpen] = useState(false);
  const [revoke, setRevoke] = useState<string | null>(null);
  const q = useApiKeys({ page, page_size: 15, active_only: activeOnly });
  const revokeKey = useApiMutation((id: string) => api(`/v1/api-keys/${id}`, { method: "DELETE", schema: apiKeySchema }), ["api-keys"]);

  return (
    <>
      <PageHeader title="API keys" description="Agents authenticate with these keys in the X-API-Key header. Only a keyed hash is stored, so a lost key must be replaced."
        actions={canManage ? <Button onClick={() => setOpen(true)}><KeyRound className="h-4 w-4" /> Generate key</Button> : undefined} />
      <Card className="!p-0">
        <FilterBar>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={activeOnly} onChange={(e) => { setActiveOnly(e.target.checked); setPage(1); }} /> Hide revoked keys</label>
        </FilterBar>
        <DataTable rows={q.data?.items} rowKey={(r) => r.id} loading={q.isLoading} error={q.error} onRetry={() => q.refetch()}
          empty={{ title: "No API keys", description: "Generate a key for an agent to start sending actions." }}
          pagination={q.data && { page: q.data.page, pages: q.data.pages, total: q.data.total, pageSize: q.data.page_size, onPage: setPage }}
          columns={[
            { header: "Name", cell: (r) => <span className="font-medium">{r.name}</span> },
            { header: "Agent", cell: (r) => r.agent_slug },
            { header: "Key", cell: (r) => <Mono>{r.prefix}…</Mono> },
            { header: "Created", cell: (r) => formatDateTime(r.created_at) },
            { header: "Last used", cell: (r) => (r.last_used_at ? formatRelative(r.last_used_at) : "Never") },
            { header: "Expires", cell: (r) => (r.expires_at ? formatDateTime(r.expires_at) : "Never") },
            { header: "Status", cell: (r) => <StatusBadge value={r.revoked_at ? "REVOKED" : "ACTIVE"} /> },
            { header: "Actions", cell: (r) => (canManage && !r.revoked_at ? <Button size="sm" variant="ghost" onClick={() => setRevoke(r.id)}>Revoke</Button> : null) },
          ]} />
      </Card>
      <ApiKeyModal open={open} onClose={() => setOpen(false)} />
      <ConfirmDialog open={!!revoke} onClose={() => setRevoke(null)} danger title="Revoke API key?" confirmLabel="Revoke key" loading={revokeKey.isPending}
        description="The agent using this key will immediately be rejected with 401. This cannot be undone."
        onConfirm={() => revoke && revokeKey.mutate(revoke, { onSuccess: () => { toast.success("Key revoked"); setRevoke(null); }, onError: (e) => toast.error(errorText(e)) })} />
    </>
  );
}
