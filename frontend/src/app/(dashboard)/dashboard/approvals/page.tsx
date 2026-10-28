"use client";

import { useState } from "react";
import { Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Mono, StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable, FilterBar } from "@/components/ui/data-table";
import { Textarea } from "@/components/ui/field";
import { ConfirmDialog } from "@/components/ui/modal";
import { errorText, useToast } from "@/components/ui/states";
import { useApiMutation, useApprovals } from "@/hooks/use-api";
import { useCan } from "@/hooks/use-role";
import { api } from "@/lib/api";
import { approvalSchema } from "@/lib/schemas";
import { formatDateTime, formatMoney, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Approval } from "@/types";

const TABS = [["PENDING", "Pending"], ["APPROVED", "Approved"], ["REJECTED", "Rejected"], ["EXPIRED", "Expired"], ["", "All"]] as const;

export default function ApprovalsPage() {
  const toast = useToast();
  const canDecide = useCan("MANAGER");
  const [status, setStatus] = useState<string>("PENDING");
  const [page, setPage] = useState(1);
  const [target, setTarget] = useState<{ approval: Approval; approve: boolean } | null>(null);
  const [reason, setReason] = useState("");
  const q = useApprovals({ page, page_size: 15, status });
  const decide = useApiMutation(
    (v: { id: string; approve: boolean; reason: string }) =>
      api(`/v1/approvals/${v.id}/${v.approve ? "approve" : "reject"}`, { method: "POST", body: { reason: v.reason || null }, schema: approvalSchema }),
    ["approvals", "actions", "analytics", "audit-logs"],
  );

  function confirm() {
    if (!target) return;
    decide.mutate({ id: target.approval.id, approve: target.approve, reason }, {
      onSuccess: () => { toast.success(target.approve ? "Action approved" : "Action rejected"); setTarget(null); setReason(""); },
      onError: (e) => { toast.error(errorText(e)); setTarget(null); void q.refetch(); },
    });
  }

  return (
    <>
      <PageHeader title="Pending approvals" description="Actions that policy says need a human decision. Agents are waiting on these, and each request expires if nobody answers in time." />
      <Card className="!p-0">
        <FilterBar>
          <div role="tablist" aria-label="Approval status" className="flex gap-1">
            {TABS.map(([value, label]) => (
              <button key={label} role="tab" aria-selected={status === value} onClick={() => { setStatus(value); setPage(1); }}
                className={cn("rounded-md px-3 py-1.5 text-sm", status === value ? "bg-ink-900 text-white" : "text-ink-700 hover:bg-paper")}>{label}</button>
            ))}
          </div>
        </FilterBar>
        <DataTable rows={q.data?.items} rowKey={(r) => r.id} loading={q.isLoading} error={q.error} onRetry={() => q.refetch()}
          empty={{ title: status === "PENDING" ? "No approvals waiting" : "Nothing in this view", description: status === "PENDING" ? "When an agent asks for something a policy gates, it shows up here." : undefined }}
          pagination={q.data && { page: q.data.page, pages: q.data.pages, total: q.data.total, pageSize: q.data.page_size, onPage: setPage }}
          columns={[
            { header: "Request", cell: (r) => (
              <div className="max-w-xs"><p className="font-mono text-xs font-medium">{r.tool}</p><p className="text-xs text-ink-400">{r.agent_slug} · {r.environment} · {formatMoney(r.estimated_cost)}</p>
                {r.reason && <p className="mt-0.5 truncate text-xs text-ink-700">“{r.reason}”</p>}</div>) },
            { header: "Why it needs approval", cell: (r) => <span className="text-xs text-ink-700">{r.policy_name ?? r.message ?? "—"}</span> },
            { header: "Arguments", cell: (r) => <Mono className="block max-w-[14rem] truncate">{JSON.stringify(r.arguments)}</Mono> },
            { header: "Status", cell: (r) => <div><StatusBadge value={r.status} /><p className="mt-0.5 text-xs text-ink-400">{r.status === "PENDING" ? `expires ${formatRelative(r.expires_at)}` : `${formatDateTime(r.decided_at)}${r.decided_by_email ? ` · ${r.decided_by_email}` : ""}`}</p></div> },
            { header: "Decision", cell: (r) => (r.status === "PENDING" && canDecide ? (
              <div className="flex gap-1.5">
                <Button size="sm" onClick={() => setTarget({ approval: r, approve: true })}><Check className="h-3.5 w-3.5" /> Approve</Button>
                <Button size="sm" variant="secondary" onClick={() => setTarget({ approval: r, approve: false })}><X className="h-3.5 w-3.5" /> Reject</Button>
              </div>) : <span className="text-xs text-ink-400">{r.decision_reason ?? ""}</span>) },
          ]} />
      </Card>
      <ConfirmDialog open={!!target} onClose={() => setTarget(null)} loading={decide.isPending} danger={target ? !target.approve : false}
        title={target?.approve ? "Approve this action?" : "Reject this action?"}
        confirmLabel={target?.approve ? "Approve action" : "Reject action"}
        description={target ? `${target.approval.agent_slug} wants to run ${target.approval.tool} in ${target.approval.environment}. ${target.approve ? "The agent will receive a one-time approval token." : "The agent will be told the request was rejected."}` : ""}
        onConfirm={confirm}>
        <Textarea aria-label="Reason" placeholder="Reason (optional, recorded in the audit log)" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
      </ConfirmDialog>
    </>
  );
}
