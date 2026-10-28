"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, Bot, ClipboardCheck, History, KeyRound, LayoutDashboard, ScrollText, Settings, ShieldHalf, Wrench } from "lucide-react";
import { Logo } from "@/components/layout/logo";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard, exact: true },
  { href: "/dashboard/approvals", label: "Pending approvals", icon: ClipboardCheck },
  { href: "/dashboard/actions", label: "Action history", icon: History },
  { href: "/dashboard/agents", label: "Agents", icon: Bot },
  { href: "/dashboard/api-keys", label: "API keys", icon: KeyRound },
  { href: "/dashboard/tools", label: "Tools", icon: Wrench },
  { href: "/dashboard/policies", label: "Policies", icon: ShieldHalf },
  { href: "/dashboard/audit-logs", label: "Audit logs", icon: ScrollText },
  { href: "/dashboard/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

export function Sidebar({ pending, onNavigate }: { pending?: number; onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="flex h-full flex-col bg-ink-950 px-3 py-4 text-ink-200">
      <div className="px-2 pb-5"><Logo light /></div>
      <ul className="space-y-0.5">
        {NAV.map(({ href, label, icon: Icon, exact }) => {
          const active = exact ? path === href : path.startsWith(href);
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn("flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors", active ? "bg-ink-700 text-white" : "hover:bg-ink-800 hover:text-white")}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                <span className="flex-1">{label}</span>
                {href.endsWith("/approvals") && !!pending && <span className="rounded-full bg-review-bg px-1.5 text-xs font-semibold text-review-fg">{pending}</span>}
              </Link>
            </li>
          );
        })}
      </ul>
      <p className="mt-auto flex items-center gap-1.5 px-2 pt-6 text-xs text-ink-400"><Activity className="h-3.5 w-3.5" aria-hidden /> Live data refreshes automatically</p>
    </nav>
  );
}
