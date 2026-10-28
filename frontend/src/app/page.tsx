import Link from "next/link";
import { Logo } from "@/components/layout/logo";

const tickets = [
  { tool: "read_logs", env: "staging", verdict: "ALLOW", tone: "bg-allow-bg text-allow-fg", note: "No policy matched" },
  { tool: "delete_database_records", env: "production", verdict: "BLOCK", tone: "bg-block-bg text-block-fg", note: "FORBIDDEN_TOOL_IN_PRODUCTION" },
  { tool: "issue_refund", env: "production", verdict: "REQUIRE APPROVAL", tone: "bg-review-bg text-review-fg", note: "Waiting for an admin · 28 min left" },
];

const points = [
  ["Policies you can read", "Block a tool, gate it by environment or cost, rate-limit an agent. Conditions are plain data, so every decision comes with a trace of what matched."],
  ["A human in the loop when it matters", "Risky actions pause in a queue. An admin approves or rejects with a reason; if nobody answers, the request expires on its own."],
  ["A record nobody can quietly edit", "Every decision lands in a hash-chained audit log. Change one row and verification points at it."],
  ["Secrets never reach the database", "Keys, tokens and passwords in action payloads are redacted before anything is stored."],
];

export default function Landing() {
  return (
    <main className="min-h-screen bg-paper">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <Logo />
        <nav className="flex items-center gap-2 text-sm">
          <Link href="/login" className="rounded-md px-3 py-2 font-medium text-ink-700 hover:bg-ink-900/5">Sign in</Link>
          <Link href="/register" className="rounded-md bg-brand px-3.5 py-2 font-medium text-white hover:bg-brand-dark">Create workspace</Link>
        </nav>
      </header>

      <section className="mx-auto grid max-w-6xl items-center gap-10 px-5 py-14 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">Your agent asks first. You decide what happens next.</h1>
          <p className="mt-5 max-w-xl text-lg text-ink-700">
            GuardRail sits between an AI agent and the action it wants to take. Every request is checked against your policies and answered with allow, block, or “ask a person”.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link href="/register" className="rounded-md bg-brand px-5 py-2.5 font-medium text-white hover:bg-brand-dark">Create a workspace</Link>
            <Link href="/login" className="rounded-md border border-line bg-white px-5 py-2.5 font-medium hover:bg-paper">Sign in to the dashboard</Link>
          </div>
        </div>
        <ol className="space-y-3" aria-label="Example decisions">
          {tickets.map((t) => (
            <li key={t.tool} className="rounded-lg border border-line bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <code className="font-mono text-sm font-medium">{t.tool}</code>
                <span className={`rounded px-2 py-0.5 text-xs font-bold ${t.tone}`}>{t.verdict}</span>
              </div>
              <p className="mt-1.5 text-xs text-ink-400">{t.env} · {t.note}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-t border-line bg-white">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-12 sm:grid-cols-2">
          {points.map(([title, body]) => (
            <div key={title}>
              <h2 className="font-semibold">{title}</h2>
              <p className="mt-1.5 text-sm text-ink-700">{body}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
