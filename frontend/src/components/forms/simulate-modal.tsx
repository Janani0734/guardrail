"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { StatusBadge, Mono } from "@/components/ui/badge";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { useAgents, useAllTools, useApiMutation } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { simulateSchema } from "@/lib/schemas";
import { errorText } from "@/components/ui/states";
import type { SimulationResult } from "@/types";

export function SimulateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const agents = useAgents({ page_size: 100 });
  const tools = useAllTools();
  const [agent, setAgent] = useState("");
  const [tool, setTool] = useState("");
  const [env, setEnv] = useState("production");
  const [cost, setCost] = useState("0");
  const [args, setArgs] = useState('{\n  "sql": "DELETE FROM sessions"\n}');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const sim = useApiMutation((body: unknown) => api("/v1/policies/simulate", { method: "POST", body, schema: simulateSchema }), []);

  function run(e: FormEvent) {
    e.preventDefault();
    let parsed: unknown;
    try {
      parsed = args.trim() ? JSON.parse(args) : {};
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error();
    } catch {
      return setError("Arguments must be a JSON object.");
    }
    if (!agent || !tool) return setError("Choose an agent and enter a tool.");
    setError(null);
    sim.mutate({ agent_id: agent, tool, environment: env, estimated_cost: Number(cost) || 0, arguments: parsed }, {
      onSuccess: setResult,
      onError: (err) => setError(errorText(err)),
    });
  }

  return (
    <Modal open={open} onClose={onClose} title="Simulate a policy decision" wide>
      <form onSubmit={run} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Agent">
            <Select value={agent} onChange={(e) => setAgent(e.target.value)}>
              <option value="">Select…</option>
              {agents.data?.items.map((a) => <option key={a.id} value={a.slug}>{a.slug}</option>)}
            </Select>
          </Field>
          <Field label="Tool">
            <Input list="sim-tools" value={tool} onChange={(e) => setTool(e.target.value)} placeholder="delete_database_records" />
            <datalist id="sim-tools">{tools.data?.items.map((t) => <option key={t.id} value={t.name} />)}</datalist>
          </Field>
          <Field label="Environment"><Input value={env} onChange={(e) => setEnv(e.target.value)} /></Field>
          <Field label="Estimated cost"><Input type="number" min={0} step="any" value={cost} onChange={(e) => setCost(e.target.value)} /></Field>
        </div>
        <Field label="Arguments (JSON)"><Textarea className="font-mono text-xs" value={args} onChange={(e) => setArgs(e.target.value)} /></Field>
        {error && <p role="alert" className="rounded-md bg-block-bg px-3 py-2 text-sm text-block-fg">{error}</p>}
        <div className="flex justify-end"><Button type="submit" loading={sim.isPending}>Run simulation</Button></div>
      </form>
      {result && (
        <div className="mt-4 space-y-2 rounded-md border border-line p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge value={result.decision} /> <Mono>{result.reason_code}</Mono>
            {result.policy_name && <span className="text-ink-400">by “{result.policy_name}”</span>}
          </div>
          {result.message && <p>{result.message}</p>}
          <ul className="space-y-1 text-xs text-ink-700">
            {result.trace.map((t, i) => (
              <li key={i} className="flex items-center gap-2">
                <span className={t.matched ? "font-semibold text-block-fg" : "text-ink-400"}>{t.matched ? "matched" : "no match"}</span>
                <span>{String(t.name ?? t.step)}</span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-ink-400">{result.note}</p>
        </div>
      )}
    </Modal>
  );
}
