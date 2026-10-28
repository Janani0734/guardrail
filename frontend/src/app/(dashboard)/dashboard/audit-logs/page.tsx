"use client";

import { useState } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Mono } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable, FilterBar } from "@/components/ui/data-table";
import { Input, Select } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { useAuditLogs, useAuditVerify } from "@/hooks/use-api";
import { useCan } from "@/hooks/use-role";
import { formatDateTime } from "@/lib/format";
import type { AuditLog } from "@/types";

export default function AuditLogsPage() {
  const isAdmin = useCan("ADMIN");
  const [page, setPage] = useState(1);
  const [event, setEvent] = useState("");
  const [entity, setEntity] = useState("");
  const [actor, setActor] = useState("");
  const [selected, setSelected] = useState<AuditLog | null>(null);
  const [verifyOn, setVerifyOn] = useState(false);
  const verify = useAuditVerify(verifyOn);
  const q = useAuditLogs({ page, page_size: 25, event_type: event, entity_type: entity, actor_type: actor });

  return (
    <>
      <PageHeader title="Audit logs" description="An append-only record of decisions, approvals and configuration changes. Each entry includes the hash of the one before it."
        actions={isAdmin ? <Button variant="secondary" loading={verify.isFetching} onClick={() => (verifyOn ? void verify.refetch() : setVerifyOn(true))}><ShieldCheck className="h-4 w-4" /> Verify integrity</Button> : undefined} />
      {verify.data && (
        <div role="status" className={`mb-4 flex items-center gap-2 rounded-md px-4 py-3 text-sm ${verify.data.valid ? "bg-allow-bg text-allow-fg" : "bg-block-bg text-block-fg"}`}>
          {verify.data.valid ? <ShieldCheck className="h-4 w-4" /> : <ShieldAlert className="h-4 w-4" />}
          {verify.data.valid ? `Chain intact: ${verify.data.checked} entries verified.` : `Tampering detected at entry #${verify.data.first_invalid_seq} (checked ${verify.data.checked}).`}
        </div>
      )}
      <Card className="!p-0">
        <FilterBar>
          <Input className="w-56" placeholder="Event, e.g. APPROVAL_APPROVED" aria-label="Event type" value={event} onChange={(e) => { setEvent(e.target.value.toUpperCase()); setPage(1); }} />
          <Select className="w-44" aria-label="Entity" value={entity} onChange={(e) => { setEntity(e.target.value); setPage(1); }}>
            <option value="">All entities</option>{["action_request", "approval", "policy", "agent", "api_key", "tool", "user", "organization"].map((x) => <option key={x}>{x}</option>)}
          </Select>
          <Select className="w-36" aria-label="Actor" value={actor} onChange={(e) => { setActor(e.target.value); setPage(1); }}>
            <option value="">Any actor</option><option value="USER">User</option><option value="AGENT">Agent</option><option value="SYSTEM">System</option>
          </Select>
        </FilterBar>
        <DataTable rows={q.data?.items} rowKey={(r) => r.id} loading={q.isLoading} error={q.error} onRetry={() => q.refetch()} onRowClick={setSelected}
          empty={{ title: "No audit entries match" }}
          pagination={q.data && { page: q.data.page, pages: q.data.pages, total: q.data.total, pageSize: q.data.page_size, onPage: setPage }}
          columns={[
            { header: "#", cell: (r) => <span className="tabular-nums text-ink-400">{r.seq}</span> },
            { header: "When", cell: (r) => formatDateTime(r.created_at) },
            { header: "Event", cell: (r) => <Mono>{r.event_type}</Mono> },
            { header: "Actor", cell: (r) => <span className="text-xs">{r.actor_label ?? r.actor_type} <span className="text-ink-400">({r.actor_type.toLowerCase()})</span></span> },
            { header: "Entity", cell: (r) => <span className="text-xs">{r.entity_type}</span> },
            { header: "Hash", cell: (r) => <Mono>{r.entry_hash.slice(0, 10)}…</Mono> },
          ]} />
      </Card>
      <Modal open={!!selected} onClose={() => setSelected(null)} title={`Audit entry #${selected?.seq ?? ""}`} wide>
        {selected && (
          <div className="space-y-3 text-sm">
            <p><Mono>{selected.event_type}</Mono> by {selected.actor_label ?? selected.actor_type} on {formatDateTime(selected.created_at)}</p>
            <pre className="max-h-64 overflow-auto rounded-md bg-paper p-3 font-mono text-xs">{JSON.stringify(selected.details, null, 2)}</pre>
            <dl className="space-y-1 text-xs"><div><dt className="text-ink-400">Previous hash</dt><dd className="break-all font-mono">{selected.prev_hash}</dd></div><div><dt className="text-ink-400">Entry hash</dt><dd className="break-all font-mono">{selected.entry_hash}</dd></div></dl>
          </div>
        )}
      </Modal>
    </>
  );
}
