"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";
import { AgentFormModal } from "@/components/forms/agent-form-modal";
import { Button } from "@/components/ui/button";
import { StatusBadge, Mono } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable, FilterBar } from "@/components/ui/data-table";
import { Input, Select } from "@/components/ui/field";
import { useAgents } from "@/hooks/use-api";
import { useCan } from "@/hooks/use-role";
import { formatDateTime } from "@/lib/format";

export default function AgentsPage() {
  const router = useRouter();
  const canCreate = useCan("MANAGER");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(false);
  const q = useAgents({ page, page_size: 15, search, status });

  return (
    <>
      <PageHeader title="Agents" description="Every AI agent that sends actions to GuardRail. Each agent has its own API keys and allowed tools."
        actions={canCreate ? <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Create agent</Button> : undefined} />
      <Card className="!p-0">
        <FilterBar>
          <Input className="max-w-xs" placeholder="Search by name or ID" aria-label="Search agents" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <Select className="w-40" aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option><option value="ACTIVE">Active</option><option value="DISABLED">Disabled</option>
          </Select>
        </FilterBar>
        <DataTable
          rows={q.data?.items} rowKey={(r) => r.id} loading={q.isLoading} error={q.error} onRetry={() => q.refetch()}
          onRowClick={(r) => router.push(`/dashboard/agents/${r.id}`)}
          empty={{ title: "No agents yet", description: "Create an agent, give it tools, then generate an API key for it.", action: canCreate ? <Button size="sm" onClick={() => setOpen(true)}>Create agent</Button> : undefined }}
          pagination={q.data && { page: q.data.page, pages: q.data.pages, total: q.data.total, pageSize: q.data.page_size, onPage: setPage }}
          columns={[
            { header: "Name", cell: (r) => <span className="font-medium">{r.name}</span> },
            { header: "Agent ID", cell: (r) => <Mono>{r.slug}</Mono> },
            { header: "Status", cell: (r) => <StatusBadge value={r.status} /> },
            { header: "Created", cell: (r) => formatDateTime(r.created_at) },
          ]}
        />
      </Card>
      <AgentFormModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}
