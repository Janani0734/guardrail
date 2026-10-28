"use client";

import Link from "next/link";
import { useState } from "react";
import { ActionDetailModal } from "@/components/action-detail";
import { ActivityChart } from "@/components/charts/charts";
import { StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader, Stat } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { ErrorState, Spinner } from "@/components/ui/states";
import { useActions, useAnalytics, useApprovals } from "@/hooks/use-api";
import { formatDateTime, formatPercent, formatRelative } from "@/lib/format";

export default function Overview() {
  const stats = useAnalytics(7);
  const recent = useActions({ page: 1, page_size: 6 });
  const pending = useApprovals({ status: "PENDING", page: 1, page_size: 5 });
  const [open, setOpen] = useState<string | null>(null);

  if (stats.isLoading) return <Spinner />;
  if (stats.isError || !stats.data) return <ErrorState error={stats.error} onRetry={() => stats.refetch()} />;
  const t = stats.data.totals;

  return (
    <>
      <PageHeader title="Overview" description="What your agents tried to do over the last 7 days, and what GuardRail decided." />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Actions evaluated" value={t.total} />
        <Stat label="Allowed" value={t.allowed} tone="allow" />
        <Stat label="Blocked" value={t.blocked} sub={`${formatPercent(t.block_rate)} of all actions`} tone="block" />
        <Stat label="Needed approval" value={t.approvals_required} tone="review" />
        <Stat label="Waiting for you" value={t.pending_approvals} sub={t.rate_limited ? `${t.rate_limited} rate-limited` : undefined} tone="review" />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card title="Activity"><ActivityChart data={stats.data.timeseries} /></Card>
        <Card title="Pending approvals" action={<Link href="/dashboard/approvals" className="text-xs font-medium text-brand underline">View all</Link>}>
          {pending.data && pending.data.items.length === 0 && <p className="py-6 text-center text-sm text-ink-400">Nothing waiting. Agents are not blocked on you.</p>}
          <ul className="space-y-2">
            {pending.data?.items.map((a) => (
              <li key={a.id} className="rounded-md border border-line p-2.5 text-sm">
                <div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-medium">{a.tool}</span><span className="text-xs text-review-fg">expires {formatRelative(a.expires_at)}</span></div>
                <p className="text-xs text-ink-400">{a.agent_slug} · {a.environment}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <Card title="Latest actions" className="mt-4" action={<Link href="/dashboard/actions" className="text-xs font-medium text-brand underline">Full history</Link>}>
        <DataTable
          rows={recent.data?.items} rowKey={(r) => r.id} loading={recent.isLoading} error={recent.error} onRetry={() => recent.refetch()}
          onRowClick={(r) => setOpen(r.id)} empty={{ title: "No actions yet", description: "Send your first request to POST /v1/actions/evaluate with an agent API key." }}
          columns={[
            { header: "Tool", cell: (r) => <span className="font-mono text-xs">{r.tool}</span> },
            { header: "Agent", cell: (r) => r.agent_slug },
            { header: "Env", cell: (r) => r.environment },
            { header: "Decision", cell: (r) => <StatusBadge value={r.status} /> },
            { header: "When", cell: (r) => formatDateTime(r.created_at) },
          ]}
        />
      </Card>
      <ActionDetailModal id={open} onClose={() => setOpen(null)} />
    </>
  );
}
