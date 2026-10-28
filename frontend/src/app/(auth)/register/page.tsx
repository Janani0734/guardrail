"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { authCall, ApiError } from "@/lib/api";
import { registerSchema } from "@/lib/schemas";

export default function RegisterPage() {
  const router = useRouter();
  const [values, setValues] = useState({ full_name: "", organization_name: "", email: "", password: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const parsed = registerSchema.safeParse(values);
    if (!parsed.success) {
      setErrors(Object.fromEntries(parsed.error.issues.map((i) => [String(i.path[0]), i.message])));
      return;
    }
    setErrors({});
    setFormError(null);
    setLoading(true);
    try {
      await authCall("register", parsed.data);
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create the account. Please try again.");
      setLoading(false);
    }
  }

  const bind = (k: keyof typeof values) => ({ value: values[k], onChange: (e: React.ChangeEvent<HTMLInputElement>) => setValues({ ...values, [k]: e.target.value }) });

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <h1 className="text-lg font-semibold">Create your workspace</h1>
      {formError && <p role="alert" className="rounded-md bg-block-bg px-3 py-2 text-sm text-block-fg">{formError}</p>}
      <Field label="Your name" error={errors.full_name}><Input autoComplete="name" {...bind("full_name")} autoFocus /></Field>
      <Field label="Organization" error={errors.organization_name}><Input autoComplete="organization" {...bind("organization_name")} /></Field>
      <Field label="Email" error={errors.email}><Input type="email" autoComplete="email" {...bind("email")} /></Field>
      <Field label="Password" error={errors.password} hint="At least 10 characters"><Input type="password" autoComplete="new-password" {...bind("password")} /></Field>
      <Button type="submit" className="w-full" loading={loading}>Create workspace</Button>
      <p className="text-center text-sm text-ink-400">Already registered? <Link href="/login" className="font-medium text-brand underline">Sign in</Link></p>
    </form>
  );
}
