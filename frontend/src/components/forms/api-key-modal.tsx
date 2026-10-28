"use client";

import { useState, type FormEvent } from "react";
import { Check, Copy, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { Mono } from "@/components/ui/badge";
import { errorText, useToast } from "@/components/ui/states";
import { useAgents, useApiMutation } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { apiKeyCreatedSchema, apiKeyFormSchema } from "@/lib/schemas";
import type { ApiKeyCreated } from "@/types";

export function ApiKeyModal({ open, onClose, agentId }: { open: boolean; onClose: () => void; agentId?: string }) {
  const toast = useToast();
  const agents = useAgents({ page_size: 100, status: "ACTIVE" });
  const [agent, setAgent] = useState(agentId ?? "");
  const [name, setName] = useState("");
  const [days, setDays] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const create = useApiMutation(
    (v: { agent: string; body: unknown }) => api(`/v1/agents/${v.agent}/api-keys`, { method: "POST", body: v.body, schema: apiKeyCreatedSchema }),
    ["api-keys"],
  );

  function close() {
    setCreated(null);
    setName("");
    setDays("");
    setCopied(false);
    onClose();
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const target = agentId ?? agent;
    const parsed = apiKeyFormSchema.safeParse({ name, expires_in_days: days === "" ? undefined : days });
    const errs: Record<string, string> = {};
    if (!target) errs.agent = "Choose an agent";
    if (!parsed.success) parsed.error.issues.forEach((i) => (errs[String(i.path[0])] = i.message));
    setErrors(errs);
    if (!parsed.success || !target) return;
    create.mutate(
      { agent: target, body: parsed.data },
      { onSuccess: (k) => setCreated(k), onError: (err) => toast.error(errorText(err)) },
    );
  }

  async function copy() {
    if (!created) return;
    await navigator.clipboard.writeText(created.key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Modal open={open} onClose={close} title={created ? "API key created" : "Generate API key"}>
      {created ? (
        <div className="space-y-3">
          <div className="flex gap-2 rounded-md bg-review-bg p-3 text-sm text-review-fg">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p>Copy this key now. GuardRail stores only a keyed hash, so it can never be shown again.</p>
          </div>
          <Mono className="block break-all p-2 text-sm">{created.key}</Mono>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={copy}>{copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} {copied ? "Copied" : "Copy key"}</Button>
            <Button onClick={close}>Done</Button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          {!agentId && (
            <Field label="Agent" error={errors.agent}>
              <Select value={agent} onChange={(e) => setAgent(e.target.value)}>
                <option value="">Select an agent…</option>
                {agents.data?.items.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.slug})</option>)}
              </Select>
            </Field>
          )}
          <Field label="Key name" error={errors.name} hint="Helps you recognise the key later, e.g. “production worker”">
            <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </Field>
          <Field label="Expires after (days, optional)" error={errors.expires_in_days}>
            <Input type="number" min={1} max={3650} value={days} onChange={(e) => setDays(e.target.value)} placeholder="Never expires" />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={close}>Cancel</Button>
            <Button type="submit" loading={create.isPending}>Generate key</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
