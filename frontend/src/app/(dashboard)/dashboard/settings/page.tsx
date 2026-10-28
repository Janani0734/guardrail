"use client";

import { useState, type FormEvent } from "react";
import { UserPlus } from "lucide-react";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Field, Input, Select } from "@/components/ui/field";
import { ConfirmDialog, Modal } from "@/components/ui/modal";
import { Spinner, errorText, useToast } from "@/components/ui/states";
import { useApiMutation, useMe, useMembers } from "@/hooks/use-api";
import { useCan } from "@/hooks/use-role";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { memberSchema, orgSchema } from "@/lib/schemas";
import type { Member, Role } from "@/types";

export default function SettingsPage() {
  const toast = useToast();
  const isAdmin = useCan("ADMIN");
  const me = useMe();
  const members = useMembers();
  const [name, setName] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [remove, setRemove] = useState<Member | null>(null);
  const [form, setForm] = useState({ email: "", full_name: "", password: "", role: "VIEWER" as Role });
  const [formError, setFormError] = useState<string | null>(null);

  const rename = useApiMutation((n: string) => api("/v1/organization", { method: "PATCH", body: { name: n }, schema: orgSchema }), ["me"]);
  const add = useApiMutation((body: typeof form) => api("/v1/members", { method: "POST", body, schema: memberSchema }), ["members"]);
  const setRole = useApiMutation((v: { id: string; role: Role }) => api(`/v1/members/${v.id}`, { method: "PATCH", body: { role: v.role }, schema: memberSchema }), ["members"]);
  const del = useApiMutation((id: string) => api(`/v1/members/${id}`, { method: "DELETE" }), ["members"]);

  if (me.isLoading || !me.data) return <Spinner />;

  function submitAdd(e: FormEvent) {
    e.preventDefault();
    const ok = z.object({ email: z.string().email(), full_name: z.string().min(1), password: z.string().min(10) }).safeParse(form);
    if (!ok.success) return setFormError("Enter a valid email, a name and a password of at least 10 characters.");
    setFormError(null);
    add.mutate(form, {
      onSuccess: () => { toast.success("Member added"); setAddOpen(false); setForm({ email: "", full_name: "", password: "", role: "VIEWER" }); },
      onError: (err) => setFormError(errorText(err)),
    });
  }

  return (
    <>
      <PageHeader title="Settings" description="Your organization and who can do what in it." />
      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Card title="Organization">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name && name.length >= 2) rename.mutate(name, { onSuccess: () => toast.success("Organization renamed"), onError: (er) => toast.error(errorText(er)) }); }}>
            <Field label="Name"><Input disabled={!isAdmin} value={name ?? me.data.organization.name} onChange={(e) => setName(e.target.value)} /></Field>
            <p className="text-xs text-ink-400">Workspace ID <code className="font-mono">{me.data.organization.slug}</code></p>
            {isAdmin && <Button type="submit" disabled={name === null || name === me.data.organization.name} loading={rename.isPending}>Save name</Button>}
          </form>
          <hr className="my-4 border-line" />
          <p className="text-sm font-medium">Signed in as</p>
          <p className="text-sm text-ink-700">{me.data.user.full_name} · {me.data.user.email}</p>
          <div className="mt-1"><StatusBadge value={me.data.role} className="bg-brand-soft text-brand-dark" /></div>
          <dl className="mt-4 space-y-1 text-xs text-ink-400">
            <div><dt className="inline font-medium text-ink-700">Admin</dt> — everything, including policies and members</div>
            <div><dt className="inline font-medium text-ink-700">Manager</dt> — agents, tools, keys and approvals</div>
            <div><dt className="inline font-medium text-ink-700">Viewer</dt> — read-only</div>
          </dl>
        </Card>
        <Card title="Members" className="!p-0" action={isAdmin ? <Button size="sm" onClick={() => setAddOpen(true)}><UserPlus className="h-3.5 w-3.5" /> Add member</Button> : undefined}>
          <DataTable rows={members.data} rowKey={(r) => r.user_id} loading={members.isLoading} error={members.error} onRetry={() => members.refetch()} empty={{ title: "No members" }}
            columns={[
              { header: "Member", cell: (r) => <div><p className="font-medium">{r.full_name}</p><p className="text-xs text-ink-400">{r.email}</p></div> },
              { header: "Role", cell: (r) => (isAdmin ? (
                <Select aria-label={`Role for ${r.email}`} className="w-32" value={r.role} onChange={(e) => setRole.mutate({ id: r.user_id, role: e.target.value as Role }, { onSuccess: () => toast.success("Role updated"), onError: (er) => toast.error(errorText(er)) })}>
                  <option>ADMIN</option><option>MANAGER</option><option>VIEWER</option>
                </Select>) : <StatusBadge value={r.role} />) },
              { header: "Joined", cell: (r) => formatDateTime(r.created_at) },
              { header: "Actions", cell: (r) => (isAdmin && r.user_id !== me.data.user.id ? <Button size="sm" variant="ghost" onClick={() => setRemove(r)}>Remove</Button> : null) },
            ]} />
        </Card>
      </div>
      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add member">
        <form onSubmit={submitAdd} className="space-y-3">
          <Field label="Full name"><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} autoFocus /></Field>
          <Field label="Email"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Temporary password" hint="Share it securely; they can sign in right away. For an existing account this is ignored."><Input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <Field label="Role"><Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}><option>VIEWER</option><option>MANAGER</option><option>ADMIN</option></Select></Field>
          {formError && <p role="alert" className="rounded-md bg-block-bg px-3 py-2 text-sm text-block-fg">{formError}</p>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button><Button type="submit" loading={add.isPending}>Add member</Button></div>
        </form>
      </Modal>
      <ConfirmDialog open={!!remove} onClose={() => setRemove(null)} danger title="Remove member?" confirmLabel="Remove member" loading={del.isPending}
        description={`${remove?.email ?? ""} will lose access to this organization immediately.`}
        onConfirm={() => remove && del.mutate(remove.user_id, { onSuccess: () => { toast.success("Member removed"); setRemove(null); }, onError: (e) => toast.error(errorText(e)) })} />
    </>
  );
}
