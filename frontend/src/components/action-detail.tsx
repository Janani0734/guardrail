"use client";

import { Modal } from "@/components/ui/modal";
import { Mono, StatusBadge } from "@/components/ui/badge";
import { ErrorState, Spinner } from "@/components/ui/states";
import { useActionDetail } from "@/hooks/use-api";
import { formatDateTime, formatMoney } from "@/lib/format";

export function ActionDetailModal({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useActionDetail(id);
  const a = q.data;
  return (
    <Modal open={!!id} onClose={onClose} title="Action details" wide>
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {a && (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge value={a.decision} /><StatusBadge value={a.status} />{a.outcome && <StatusBadge value={a.outcome} />}<Mono>{a.reason_code ?? "—"}</Mono></div>
          {a.message && <p>{a.message}</p>}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
            {[["Action ID", a.action_id], ["Agent", a.agent_slug], ["Tool", a.tool], ["Environment", a.environment],
              ["Estimated cost", formatMoney(a.estimated_cost)], ["Policy", a.policy_name ?? "None (default)"],
              ["Received", formatDateTime(a.created_at)], ["Latency", a.latency_ms != null ? `${a.latency_ms} ms` : "—"],
              ["Secrets redacted", String(a.secrets_redacted)]].map(([k, v]) => (
              <div key={k}><dt className="text-xs text-ink-400">{k}</dt><dd className="break-words font-medium">{v}</dd></div>
            ))}
          </dl>
          {a.reason && <div><p className="text-xs text-ink-400">Agent's stated reason</p><p>{a.reason}</p></div>}
          <div>
            <p className="mb-1 text-xs text-ink-400">Arguments (secrets redacted)</p>
            <pre className="max-h-48 overflow-auto rounded-md bg-paper p-3 font-mono text-xs">{JSON.stringify(a.arguments, null, 2)}</pre>
          </div>
          <div>
            <p className="mb-1 text-xs text-ink-400">Evaluation trace</p>
            <ul className="space-y-1 text-xs">
              {a.trace.map((t, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2 rounded border border-line px-2 py-1">
                  <span className="font-mono text-ink-400">{String(t.step)}</span>
                  {t.name != null && <span className="font-medium">{String(t.name)}</span>}
                  {typeof t.matched === "boolean" && <span className={t.matched ? "font-semibold text-block-fg" : "text-ink-400"}>{t.matched ? "matched" : "no match"}</span>}
                  {t.retry_after_seconds != null && <span>retry in {String(t.retry_after_seconds)}s</span>}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Modal>
  );
}
