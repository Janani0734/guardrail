"use client";

import { Suspense, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { authCall, ApiError } from "@/lib/api";
import { loginSchema } from "@/lib/schemas";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [values, setValues] = useState({ email: "", password: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const parsed = loginSchema.safeParse(values);
    if (!parsed.success) {
      setErrors(Object.fromEntries(parsed.error.issues.map((i) => [String(i.path[0]), i.message])));
      return;
    }
    setErrors({});
    setFormError(null);
    setLoading(true);
    try {
      await authCall("login", parsed.data);
      const next = params.get("next");
      router.replace(next && next.startsWith("/dashboard") ? next : "/dashboard");
      router.refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not sign in. Please try again.");
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <h1 className="text-lg font-semibold">Sign in</h1>
      {formError && <p role="alert" className="rounded-md bg-block-bg px-3 py-2 text-sm text-block-fg">{formError}</p>}
      <Field label="Email" error={errors.email}>
        <Input type="email" autoComplete="email" value={values.email} onChange={(e) => setValues({ ...values, email: e.target.value })} autoFocus />
      </Field>
      <Field label="Password" error={errors.password}>
        <Input type="password" autoComplete="current-password" value={values.password} onChange={(e) => setValues({ ...values, password: e.target.value })} />
      </Field>
      <Button type="submit" className="w-full" loading={loading}>Sign in</Button>
      <p className="text-center text-sm text-ink-400">New here? <Link href="/register" className="font-medium text-brand underline">Create a workspace</Link></p>
    </form>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
