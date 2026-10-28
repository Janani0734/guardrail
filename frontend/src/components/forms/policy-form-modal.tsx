"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { errorText, useToast } from "@/components/ui/states";
import { useApiMutation } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { policySchema } from "@/lib/schemas";
import type { Decision, Operator, Policy, PolicyType } from "@/types";

interface RuleRow { field: string; operator: Operator; value: string }
interface FormState {
  name: string; description: string; policy_type: PolicyType; effect: Decision; priority: string; reason_code: string;
  message: string; is_active: boolean; limit: string; window_seconds: string; scope: string; threshold: string;
  block_seconds: string; ttl_minutes: string; rules: RuleRow[];
}

const OPERATORS: Operator[] = ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "contains", "not_contains", "startswith", "regex"];
const FIELDS = ["tool", "environment", "estimated_cost", "agent_id", "reason", "arguments_text", "arguments.<key>"];

const EMPTY: FormState = {
  name: "", description: "", policy_type: "RULE", effect: "BLOCK", priority: "100", reason_code: "POLICY_MATCH", message: "",
  is_active: true, limit: "20", window_seconds: "60", scope: "agent", threshold: "3", block_seconds: "300", ttl_minutes: "",
  rules: [{ field: "tool", operator: "eq", value: "" }],
};

const TEMPLATES: { label: string; patch: Partial<FormState> }[] = [
  { label: "Block a tool globally", patch: { name: "Block <tool> globally", effect: "BLOCK", reason_code: "FORBIDDEN_TOOL", rules: [{ field: "tool", operator: "eq", value: "format_disk" }] } },
  { label: "Block a tool in one environment", patch: { name: "Block <tool> in production", effect: "BLOCK", reason_code: "FORBIDDEN_TOOL_IN_PRODUCTION", rules: [{ field: "tool", operator: "eq", value: "delete_database_records" }, { field: "environment", operator: "eq", value: "production" }] } },
  { label: "Require approval for a tool", patch: { name: "Approve <tool>", effect: "REQUIRE_APPROVAL", reason_code: "APPROVAL_REQUIRED", rules: [{ field: "tool", operator: "eq", value: "send_email" }] } },
  { label: "Require approval above a cost", patch: { name: "Costly actions need approval", effect: "REQUIRE_APPROVAL", reason_code: "HIGH_COST", rules: [{ field: "estimated_cost", operator: "gt", value: "10" }] } },
  { label: "Production approval for selected tools", patch: { name: "Production approval for risky tools", effect: "REQUIRE_APPROVAL", reason_code: "PROD_APPROVAL", rules: [{ field: "tool", operator: "in", value: "issue_refund, deploy_service" }, { field: "environment", operator: "eq", value: "production" }] } },
  { label: "Always block DROP TABLE", patch: { name: "Never allow DROP TABLE", effect: "BLOCK", reason_code: "DROP_TABLE_FORBIDDEN", rules: [{ field: "arguments_text", operator: "regex", value: "\\bDROP\\s+TABLE\\b" }] } },
  { label: "Rate limit per agent", patch: { name: "20 actions per minute", policy_type: "RATE_LIMIT", effect: "BLOCK", reason_code: "RATE_LIMIT_EXCEEDED", rules: [] } },
  { label: "Block unknown tools", patch: { name: "Block unknown tools", policy_type: "UNKNOWN_TOOL", effect: "BLOCK", reason_code: "UNKNOWN_TOOL", rules: [] } },
  { label: "Temporarily block repeated failures", patch: { name: "Repeated failures", policy_type: "REPEATED_ACTION", effect: "BLOCK", reason_code: "REPEATED_ACTION_BLOCKED", rules: [] } },
];

function valueToText(v: unknown): string {
  return Array.isArray(v) ? v.join(", ") : v === null || v === undefined ? "" : String(v);
}

function textToValue(op: Operator, text: string): unknown {
  if (op === "in" || op === "not_in") return text.split(",").map((x) => x.trim()).filter(Boolean);
  if (["gt", "gte", "lt", "lte"].includes(op)) return Number(text);
  return text;
}

function fromPolicy(p: Policy): FormState {
  const c = p.config;
  return {
    ...EMPTY, name: p.name, description: p.description ?? "", policy_type: p.policy_type, effect: p.effect, priority: String(p.priority),
    reason_code: p.reason_code, message: p.message ?? "", is_active: p.is_active,
    limit: String(c.limit ?? "20"), window_seconds: String(c.window_seconds ?? (p.policy_type === "REPEATED_ACTION" ? "600" : "60")),
    scope: String(c.scope ?? "agent"), threshold: String(c.threshold ?? "3"), block_seconds: String(c.block_seconds ?? "300"),
    ttl_minutes: c.ttl_minutes ? String(c.ttl_minutes) : "",
    rules: p.rules.map((r) => ({ field: r.field, operator: r.operator, value: valueToText(r.value) })),
  };
}

export function PolicyFormModal({ open, onClose, policy }: { open: boolean; onClose: () => void; policy?: Policy | null }) {
  const toast = useToast();
  const [f, setF] = useState<FormState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const save = useApiMutation(
    (body: unknown) => api(policy ? `/v1/policies/${policy.id}` : "/v1/policies", { method: policy ? "PATCH" : "POST", body, schema: policySchema }),
    ["policies"],
  );

  useEffect(() => {
    if (open) {
      setF(policy ? fromPolicy(policy) : EMPTY);
      setError(null);
    }
  }, [open, policy]);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));
  const isRule = f.policy_type === "RULE";

  function config(): Record<string, unknown> {
    if (f.policy_type === "RATE_LIMIT") return { limit: Number(f.limit), window_seconds: Number(f.window_seconds), scope: f.scope };
    if (f.policy_type === "REPEATED_ACTION") return { threshold: Number(f.threshold), window_seconds: Number(f.window_seconds), block_seconds: Number(f.block_seconds) };
    if (isRule && f.effect === "REQUIRE_APPROVAL" && f.ttl_minutes) return { ttl_minutes: Number(f.ttl_minutes) };
    return {};
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.name.trim().length < 2) return setError("Give the policy a name (2+ characters).");
    if (!/^[A-Z0-9_]{2,64}$/.test(f.reason_code)) return setError("Reason code must be UPPER_SNAKE_CASE.");
    if (isRule && f.rules.some((r) => !r.field || r.value.trim() === "")) return setError("Every rule needs a field and a value.");
    const body = {
      name: f.name.trim(), description: f.description || null, effect: f.effect, priority: Number(f.priority) || 0,
      is_active: f.is_active, reason_code: f.reason_code, message: f.message || null, config: config(),
      rules: isRule ? f.rules.map((r) => ({ field: r.field, operator: r.operator, value: textToValue(r.operator, r.value) })) : [],
      ...(policy ? {} : { policy_type: f.policy_type }),
    };
    setError(null);
    save.mutate(body, {
      onSuccess: () => {
        toast.success(policy ? "Policy updated" : "Policy created");
        onClose();
      },
      onError: (err) => setError(errorText(err)),
    });
  }

  return (
    <Modal open={open} onClose={onClose} title={policy ? "Edit policy" : "Create policy"} wide>
      <form onSubmit={submit} className="space-y-3">
        {!policy && (
          <Field label="Start from a template">
            <Select value="" onChange={(e) => { const t = TEMPLATES[Number(e.target.value)]; if (t) setF({ ...EMPTY, ...t.patch }); }}>
              <option value="">Choose a template (optional)…</option>
              {TEMPLATES.map((t, i) => <option key={t.label} value={i}>{t.label}</option>)}
            </Select>
          </Field>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><Input value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
          <Field label="Priority" hint="Lower numbers are evaluated first"><Input type="number" min={0} value={f.priority} onChange={(e) => set("priority", e.target.value)} /></Field>
          <Field label="Type">
            <Select value={f.policy_type} disabled={!!policy} onChange={(e) => set("policy_type", e.target.value as PolicyType)}>
              <option value="RULE">Rule-based</option><option value="RATE_LIMIT">Rate limit</option>
              <option value="UNKNOWN_TOOL">Block unknown tools</option><option value="REPEATED_ACTION">Repeated failure guard</option>
            </Select>
          </Field>
          <Field label="Effect">
            <Select value={f.effect} disabled={!isRule} onChange={(e) => set("effect", e.target.value as Decision)}>
              <option value="BLOCK">BLOCK</option><option value="REQUIRE_APPROVAL">REQUIRE_APPROVAL</option><option value="ALLOW">ALLOW</option>
            </Select>
          </Field>
          <Field label="Reason code"><Input value={f.reason_code} onChange={(e) => set("reason_code", e.target.value.toUpperCase())} /></Field>
          <Field label="Message returned to the agent"><Input value={f.message} onChange={(e) => set("message", e.target.value)} /></Field>
        </div>

        {isRule && (
          <div className="space-y-2 rounded-md border border-line p-3">
            <p className="text-sm font-medium">Conditions <span className="font-normal text-ink-400">— all must match</span></p>
            {f.rules.map((r, i) => (
              <div key={i} className="grid grid-cols-[1fr_auto_1.4fr_auto] items-center gap-2">
                <Input list="rule-fields" aria-label="Field" value={r.field} onChange={(e) => set("rules", f.rules.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))} />
                <Select aria-label="Operator" value={r.operator} onChange={(e) => set("rules", f.rules.map((x, j) => (j === i ? { ...x, operator: e.target.value as Operator } : x)))}>
                  {OPERATORS.map((o) => <option key={o}>{o}</option>)}
                </Select>
                <Input aria-label="Value" value={r.value} placeholder={r.operator === "in" || r.operator === "not_in" ? "a, b, c" : "value"} onChange={(e) => set("rules", f.rules.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                <Button type="button" variant="ghost" size="sm" aria-label="Remove condition" disabled={f.rules.length === 1} onClick={() => set("rules", f.rules.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
            <datalist id="rule-fields">{FIELDS.map((x) => <option key={x} value={x} />)}</datalist>
            <Button type="button" variant="secondary" size="sm" onClick={() => set("rules", [...f.rules, { field: "tool", operator: "eq", value: "" }])}><Plus className="h-3.5 w-3.5" /> Add condition</Button>
            {f.effect === "REQUIRE_APPROVAL" && (
              <Field label="Approval window (minutes, optional)" hint="Defaults to the server setting"><Input type="number" min={1} value={f.ttl_minutes} onChange={(e) => set("ttl_minutes", e.target.value)} /></Field>
            )}
          </div>
        )}
        {f.policy_type === "RATE_LIMIT" && (
          <div className="grid gap-3 rounded-md border border-line p-3 sm:grid-cols-3">
            <Field label="Max actions"><Input type="number" min={1} value={f.limit} onChange={(e) => set("limit", e.target.value)} /></Field>
            <Field label="Window (seconds)"><Input type="number" min={1} value={f.window_seconds} onChange={(e) => set("window_seconds", e.target.value)} /></Field>
            <Field label="Counted per"><Select value={f.scope} onChange={(e) => set("scope", e.target.value)}><option value="agent">Agent</option><option value="api_key">API key</option></Select></Field>
          </div>
        )}
        {f.policy_type === "REPEATED_ACTION" && (
          <div className="grid gap-3 rounded-md border border-line p-3 sm:grid-cols-3">
            <Field label="Failures before block"><Input type="number" min={1} value={f.threshold} onChange={(e) => set("threshold", e.target.value)} /></Field>
            <Field label="Counting window (s)"><Input type="number" min={1} value={f.window_seconds} onChange={(e) => set("window_seconds", e.target.value)} /></Field>
            <Field label="Block duration (s)"><Input type="number" min={1} value={f.block_seconds} onChange={(e) => set("block_seconds", e.target.value)} /></Field>
          </div>
        )}
        <Field label="Description (optional)"><Textarea value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} /> Policy is active</label>
        {error && <p role="alert" className="rounded-md bg-block-bg px-3 py-2 text-sm text-block-fg">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending}>{policy ? "Save changes" : "Create policy"}</Button>
        </div>
      </form>
    </Modal>
  );
}
