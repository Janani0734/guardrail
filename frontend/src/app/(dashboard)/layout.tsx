"use client";

import { useState, type ReactNode } from "react";
import { LogOut, Menu } from "lucide-react";
import { Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { Spinner, ErrorState } from "@/components/ui/states";
import { StatusBadge } from "@/components/ui/badge";
import { useAnalytics, useMe } from "@/hooks/use-api";
import { logout } from "@/lib/api";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const me = useMe();
  const stats = useAnalytics(1);
  const [open, setOpen] = useState(false);

  if (me.isLoading) return <div className="min-h-screen"><Spinner label="Loading your workspace…" /></div>;
  if (me.isError || !me.data) return <div className="min-h-screen"><ErrorState error={me.error} onRetry={() => me.refetch()} /></div>;

  const pending = stats.data?.totals.pending_approvals;
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="hidden lg:block"><div className="sticky top-0 h-screen"><Sidebar pending={pending} /></div></aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-ink-950/50" />
          <div className="relative h-full w-64" onClick={(e) => e.stopPropagation()}><Sidebar pending={pending} onNavigate={() => setOpen(false)} /></div>
        </div>
      )}
      <div className="min-w-0">
        <header className="flex items-center justify-between border-b border-line bg-white px-4 py-2.5">
          <Button variant="ghost" size="sm" className="lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu className="h-5 w-5" /></Button>
          <p className="hidden text-sm font-medium lg:block">{me.data.organization.name}</p>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-ink-400 sm:inline">{me.data.user.email}</span>
            <StatusBadge value={me.data.role} className="bg-brand-soft text-brand-dark" />
            <Button variant="secondary" size="sm" onClick={() => void logout()}><LogOut className="h-3.5 w-3.5" /> Sign out</Button>
          </div>
        </header>
        <main className="mx-auto max-w-6xl p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
