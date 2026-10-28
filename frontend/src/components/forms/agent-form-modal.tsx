"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { errorText, useToast } from "@/components/ui/states";
import { useApiMutation } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { agentFormSchema, agentSchema } from "@/lib/schemas";

export function AgentFormModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [values, setValues] = useState({ slug: "", name: "", description: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useApiMutation((body: unknown) => api("/v1/agents", { method: "POST", body, schema: agentSchema }), ["agents"]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const parsed = agentFormSchema.safeParse(values);
    if (!parsed.success) {
      setErrors(Object.fromEntries(parsed.error.issues.map((i) => [String(i.path[0]), i.message])));
      return;
    }
    setErrors({});
    create.mutate(
      { ...parsed.data, description: parsed.data.description || null },
      {
        onSuccess: (a) => {
          toast.success(`Agent ${a.slug} created`);
          setValues({ slug: "", name: "", description: "" });
          onClose();
        },
        onError: (err) => toast.error(errorText(err)),
      },
    );
  }

  return (
    <Modal open={open} onClose={onClose} title="Create agent">
      <form onSubmit={submit} className="space-y-3">
        <Field label="Agent ID" error={errors.slug} hint="The identifier the agent sends as agent_id, e.g. support-agent-01">
          <Input value={values.slug} onChange={(e) => setValues({ ...values, slug: e.target.value })} placeholder="support-agent-01" autoFocus />
        </Field>
        <Field label="Display name" error={errors.name}>
          <Input value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} placeholder="Support agent" />
        </Field>
        <Field label="Description (optional)" error={errors.description}>
          <Textarea value={values.description} onChange={(e) => setValues({ ...values, description: e.target.value })} />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create agent</Button>
        </div>
      </form>
    </Modal>
  );
}
