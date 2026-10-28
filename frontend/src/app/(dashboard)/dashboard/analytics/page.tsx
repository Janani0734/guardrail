"use client";

import { useState } from "react";
import { ActivityChart, AgentActivityChart, ReasonChart, ToolChart } from "@/components/charts/charts";
import { Card, PageHeader, Stat } from "@/components/ui/card";
import { Select } from "@/components/ui/field";
import { EmptyState, ErrorState, Spinner } from "@/components/ui/states";
import { useAnalytics } from "@/hooks/use-api";
import { formatPercent } from "@/lib/format";

export default function AnalyticsPage() {
  const [days, setDays] = useState(7);
  const q = useAnalytics(days);

  return (
    <>
      <PageHeader title="Analytics" description="Trends in what agents attempt and how often policies step in."
        actions={<Select aria-label="Time range" className="w-40" value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></Select>} />
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.data && (q.data.totals.total === 0 ? <EmptyState title="No activity in this period" description="Charts appear as soon as agents start sending actions." /> : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Total actions" value={q.data.totals.total} />
            <Stat label="Blocked" value={q.data.totals.blocked} sub={formatPercent(q.data.totals.block_rate)} tone="block" />
            <Stat label="Approvals requested" value={q.data.totals.approvals_required} sub={`${q.data.approvals.APPROVED ?? 0} approved · ${q.data.approvals.REJECTED ?? 0} rejected · ${q.data.approvals.EXPIRED ?? 0} expired`} tone="review" />
            <Stat label="Secrets redacted" value={q.data.totals.secrets_redacted} sub={`${q.data.totals.rate_limited} rate-limit hits`} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card title="Total actions over time" className="lg:col-span-2"><ActivityChart data={q.data.timeseries} /></Card>
            <Card title="Agent activity"><AgentActivityChart data={q.data.agent_activity} /></Card>
            <Card title="Most used tools"><ToolChart data={q.data.top_tools} /></Card>
            <Card title="Why actions were blocked" className="lg:col-span-2">{q.data.block_reasons.length ? <ReasonChart data={q.data.block_reasons} /> : <p className="py-8 text-center text-sm text-ink-400">No blocked actions in this period.</p>}</Card>
          </div>
        </>
      ))}
    </>
  );
}
