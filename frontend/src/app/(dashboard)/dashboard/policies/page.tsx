"use client";

import { useState } from "react";
import { FlaskConical, Plus } from "lucide-react";
import { PolicyFormModal } from "@/components/forms/policy-form-modal";
import { SimulateModal } from "@/components/forms/simulate-modal";
import { Button } from "@/components/ui/button";
import { Mono, StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable, FilterBar } from "@/components/ui/data-table";
import { Input, Select } from "@/components/ui/field";
import { ConfirmDialog } from "@/components/ui/modal";
import { errorText, useToast } from "@/components/ui/states";
import { useApiMutation, usePolicies } from "@/hooks/use-api";
import { useCan } from "@/hooks/use-role";
import { api } from "@/lib/api";
import { policySchema } from "@/lib/schemas";
import type { Policy } from "@/types";

function summary(p: Policy): string {
  if (p.policy_type === "RATE_LIMIT") return `${String(p.config.limit)} per ${String(p.config.window_seconds)}s per ${String(p.config.scope)}`;
  if (p.policy_type === "REPEATED_ACTION") return `${String(p.config.threshold)} repeats → block ${String(p.config.block_seconds)}s`;
  if (p.policy_type === "UNKNOWN_TOOL") return "Tools not registered for the agent";
  return p.rules.map((r) => `${r.field} ${r.operator} ${Array.isArray(r.value) ? `[${r.value.join(", ")}]` : String(r.value)}`).join(" AND ");
}

export default function PoliciesPage() {
  const toast = useToast();
  const isAdmin = useCan("ADMIN");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [effect, setEffect] = useState("");
  const [type, setType] = useState("");
  const [editing, setEditing] = useState<Policy | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [simOpen, setSimOpen] = useState(false);
  const [del, setDel] = useState<Policy | null>(null);
  const q = usePolicies({ page, page_size: 15, search, effect, policy_type: type });
  const toggle = useApiMutation((v: { id: string; is_active: boolean }) => api(`/v1/policies/${v.id}`, { method: "PATCH", body: { is_active: v.is_active }, schema: policySchema }), ["policies"]);
  const remove = useApiMutation((id: string) => api(`/v1/policies/${id}`, { method: "DELETE" }), ["policies"]);

  return (
    <>
      <PageHeader title="Policies" description="Rules are checked in priority order (lowest number first). If several match, BLOCK beats REQUIRE_APPROVAL beats ALLOW."
        actions={<>
          <Button variant="secondary" onClick={() => setSimOpen(true)}><FlaskConical className="h-4 w-4" /> Simulate</Button>
          {isAdmin && <Button onClick={() => { setEditing(null); setFormOpen(true); }}><Plus className="h-4 w-4" /> Create policy</Button>}
        </>} />
      <Card className="!p-0">
        <FilterBar>
          <Input className="max-w-xs" placeholder="Search policies" aria-label="Search policies" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <Select className="w-44" aria-label="Type" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
            <option value="">All types</option><option value="RULE">Rule-based</option><option value="RATE_LIMIT">Rate limit</option><option value="UNKNOWN_TOOL">Unknown tool</option><option value="REPEATED_ACTION">Repeated action</option>
          </Select>
          <Select className="w-44" aria-label="Effect" value={effect} onChange={(e) => { setEffect(e.target.value); setPage(1); }}>
            <option value="">All effects</option><option value="BLOCK">Block</option><option value="REQUIRE_APPROVAL">Require approval</option><option value="ALLOW">Allow</option>
          </Select>
        </FilterBar>
        <DataTable rows={q.data?.items} rowKey={(r) => r.id} loading={q.isLoading} error={q.error} onRetry={() => q.refetch()}
          empty={{ title: "No policies yet", description: "Without policies every registered, assigned tool is allowed. Add a policy to start governing actions.", action: isAdmin ? <Button size="sm" onClick={() => { setEditing(null); setFormOpen(true); }}>Create policy</Button> : undefined }}
          pagination={q.data && { page: q.data.page, pages: q.data.pages, total: q.data.total, pageSize: q.data.page_size, onPage: setPage }}
          columns={[
            { header: "Priority", cell: (r) => <span className="tabular-nums">{r.priority}</span> },
            { header: "Policy", cell: (r) => <div className="max-w-sm"><p className="font-medium">{r.name}</p><p className="truncate text-xs text-ink-400">{summary(r)}</p></div> },
            { header: "Type", cell: (r) => <span className="text-xs">{r.policy_type.replace("_", " ")}</span> },
            { header: "Effect", cell: (r) => <StatusBadge value={r.effect} /> },
            { header: "Reason code", cell: (r) => <Mono>{r.reason_code}</Mono> },
            { header: "Active", cell: (r) => (isAdmin ? (
              <input type="checkbox" aria-label={`Toggle ${r.name}`} checked={r.is_active}
                onChange={(e) => toggle.mutate({ id: r.id, is_active: e.target.checked }, { onError: (err) => toast.error(errorText(err)) })} />
            ) : <StatusBadge value={r.is_active ? "ACTIVE" : "DISABLED"} />) },
            { header: "Actions", cell: (r) => (isAdmin ? (
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => { setEditing(r); setFormOpen(true); }}>Edit</Button>
                <Button size="sm" variant="ghost" onClick={() => setDel(r)}>Delete</Button>
              </div>) : null) },
          ]} />
      </Card>
      <PolicyFormModal open={formOpen} onClose={() => setFormOpen(false)} policy={editing} />
      <SimulateModal open={simOpen} onClose={() => setSimOpen(false)} />
      <ConfirmDialog open={!!del} onClose={() => setDel(null)} danger title="Delete policy?" confirmLabel="Delete policy" loading={remove.isPending}
        description={`“${del?.name ?? ""}” will stop applying immediately. Past decisions keep their record, and the deletion is written to the audit log. Consider disabling it instead.`}
        onConfirm={() => del && remove.mutate(del.id, { onSuccess: () => { toast.success("Policy deleted"); setDel(null); }, onError: (e) => toast.error(errorText(e)) })} />
    </>
  );
}
