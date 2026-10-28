"use client";

import { useState } from "react";
import { ActionDetailModal } from "@/components/action-detail";
import { StatusBadge, Mono } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable, FilterBar } from "@/components/ui/data-table";
import { Input, Select } from "@/components/ui/field";
import { useActions, useAgents } from "@/hooks/use-api";
import { formatDateTime, formatMoney } from "@/lib/format";

export default function ActionHistoryPage() {
  const [page, setPage] = useState(1);
  const [f, setF] = useState({ search: "", tool: "", environment: "", decision: "", status: "", agent_id: "", sort_by: "created_at", order: "desc" });
  const [open, setOpen] = useState<string | null>(null);
  const agents = useAgents({ page_size: 100 });
  const q = useActions({ page, page_size: 20, ...f });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(1); };

  return (
    <>
      <PageHeader title="Action history" description="Every request agents have sent, with the decision and the policy that made it. Click a row for the full evaluation trace." />
      <Card className="!p-0">
        <FilterBar>
          <Input className="w-40" placeholder="Action ID" aria-label="Action ID" value={f.search} onChange={set("search")} />
          <Input className="w-40" placeholder="Tool" aria-label="Tool" value={f.tool} onChange={set("tool")} />
          <Select className="w-40" aria-label="Agent" value={f.agent_id} onChange={set("agent_id")}><option value="">All agents</option>{agents.data?.items.map((a) => <option key={a.id} value={a.id}>{a.slug}</option>)}</Select>
          <Select className="w-36" aria-label="Environment" value={f.environment} onChange={set("environment")}><option value="">All envs</option><option>production</option><option>staging</option><option>development</option></Select>
          <Select className="w-44" aria-label="Decision" value={f.decision} onChange={set("decision")}><option value="">All decisions</option><option value="ALLOW">Allow</option><option value="BLOCK">Block</option><option value="REQUIRE_APPROVAL">Require approval</option></Select>
          <Select className="w-44" aria-label="Status" value={f.status} onChange={set("status")}><option value="">Any status</option>{["ALLOWED", "BLOCKED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXPIRED"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</Select>
          <Select className="w-44" aria-label="Sort" value={`${f.sort_by}:${f.order}`} onChange={(e) => { const [sort_by = "created_at", order = "desc"] = e.target.value.split(":"); setF({ ...f, sort_by, order }); setPage(1); }}>
            <option value="created_at:desc">Newest first</option><option value="created_at:asc">Oldest first</option><option value="estimated_cost:desc">Highest cost</option><option value="tool:asc">Tool A–Z</option>
          </Select>
        </FilterBar>
        <DataTable rows={q.data?.items} rowKey={(r) => r.id} loading={q.isLoading} error={q.error} onRetry={() => q.refetch()} onRowClick={(r) => setOpen(r.id)}
          empty={{ title: "No actions match", description: "Try clearing a filter, or send a request to POST /v1/actions/evaluate." }}
          pagination={q.data && { page: q.data.page, pages: q.data.pages, total: q.data.total, pageSize: q.data.page_size, onPage: setPage }}
          columns={[
            { header: "When", cell: (r) => formatDateTime(r.created_at) },
            { header: "Action", cell: (r) => <Mono>{r.action_id}</Mono> },
            { header: "Agent", cell: (r) => r.agent_slug },
            { header: "Tool", cell: (r) => <span className="font-mono text-xs">{r.tool}</span> },
            { header: "Env", cell: (r) => r.environment },
            { header: "Cost", cell: (r) => <span className="tabular-nums">{formatMoney(r.estimated_cost)}</span> },
            { header: "Decision", cell: (r) => <StatusBadge value={r.status} /> },
            { header: "Reason", cell: (r) => <span className="text-xs text-ink-700">{r.reason_code ?? "—"}</span> },
          ]} />
      </Card>
      <ActionDetailModal id={open} onClose={() => setOpen(null)} />
    </>
  );
}
