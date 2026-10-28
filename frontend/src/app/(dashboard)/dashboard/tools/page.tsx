"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { ToolFormModal } from "@/components/forms/tool-form-modal";
import { Button } from "@/components/ui/button";
import { Mono, StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable, FilterBar } from "@/components/ui/data-table";
import { Input } from "@/components/ui/field";
import { errorText, useToast } from "@/components/ui/states";
import { useApiMutation, useTools } from "@/hooks/use-api";
import { useCan } from "@/hooks/use-role";
import { api } from "@/lib/api";
import { toolSchema } from "@/lib/schemas";

export default function ToolsPage() {
  const toast = useToast();
  const canManage = useCan("MANAGER");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const q = useTools({ page, page_size: 15, search });
  const toggle = useApiMutation((v: { id: string; is_active: boolean }) => api(`/v1/tools/${v.id}`, { method: "PATCH", body: { is_active: v.is_active }, schema: toolSchema }), ["tools", "tools-all", "agent-tools"]);

  return (
    <>
      <PageHeader title="Tools" description="The actions your agents are allowed to ask for. A tool that isn't registered here is treated as unknown and blocked."
        actions={canManage ? <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Register tool</Button> : undefined} />
      <Card className="!p-0">
        <FilterBar><Input className="max-w-xs" placeholder="Search tools" aria-label="Search tools" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} /></FilterBar>
        <DataTable rows={q.data?.items} rowKey={(r) => r.id} loading={q.isLoading} error={q.error} onRetry={() => q.refetch()}
          empty={{ title: "No tools registered", description: "Register the tools your agents use, then assign them on each agent's page." }}
          pagination={q.data && { page: q.data.page, pages: q.data.pages, total: q.data.total, pageSize: q.data.page_size, onPage: setPage }}
          columns={[
            { header: "Tool", cell: (r) => <Mono>{r.name}</Mono> },
            { header: "Risk", cell: (r) => <StatusBadge value={r.risk_level} /> },
            { header: "Description", cell: (r) => <span className="text-ink-700">{r.description ?? "—"}</span> },
            { header: "Status", cell: (r) => <StatusBadge value={r.is_active ? "ACTIVE" : "DISABLED"} /> },
            { header: "Actions", cell: (r) => (canManage ? (
              <Button size="sm" variant="ghost" onClick={() => toggle.mutate({ id: r.id, is_active: !r.is_active }, { onSuccess: () => toast.success(r.is_active ? "Tool disabled" : "Tool enabled"), onError: (e) => toast.error(errorText(e)) })}>
                {r.is_active ? "Disable" : "Enable"}
              </Button>) : null) },
          ]} />
      </Card>
      <ToolFormModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}
