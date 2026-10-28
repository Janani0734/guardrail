"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { errorText, useToast } from "@/components/ui/states";
import { useApiMutation } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { toolFormSchema, toolSchema } from "@/lib/schemas";
import type { RiskLevel } from "@/types";

export function ToolFormModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [values, setValues] = useState<{ name: string; description: string; risk_level: RiskLevel }>({ name: "", description: "", risk_level: "LOW" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useApiMutation((body: unknown) => api("/v1/tools", { method: "POST", body, schema: toolSchema }), ["tools", "tools-all"]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const parsed = toolFormSchema.safeParse(values);
    if (!parsed.success) {
      setErrors(Object.fromEntries(parsed.error.issues.map((i) => [String(i.path[0]), i.message])));
      return;
    }
    setErrors({});
    create.mutate(
      { ...parsed.data, description: parsed.data.description || null },
      {
        onSuccess: (t) => {
          toast.success(`Tool ${t.name} registered`);
          setValues({ name: "", description: "", risk_level: "LOW" });
          onClose();
        },
        onError: (err) => toast.error(errorText(err)),
      },
    );
  }

  return (
    <Modal open={open} onClose={onClose} title="Register tool">
      <form onSubmit={submit} className="space-y-3">
        <Field label="Tool name" error={errors.name} hint="Exactly what agents send in the tool field">
          <Input value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} placeholder="delete_database_records" autoFocus />
        </Field>
        <Field label="Risk level" error={errors.risk_level}>
          <Select value={values.risk_level} onChange={(e) => setValues({ ...values, risk_level: e.target.value as RiskLevel })}>
            {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((r) => <option key={r}>{r}</option>)}
          </Select>
        </Field>
        <Field label="Description (optional)" error={errors.description}>
          <Textarea value={values.description} onChange={(e) => setValues({ ...values, description: e.target.value })} />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Register tool</Button>
        </div>
      </form>
    </Modal>
  );
}
