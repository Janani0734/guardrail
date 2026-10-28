import { ShieldCheck } from "lucide-react";

export function Logo({ light }: { light?: boolean }) {
  return (
    <span className={`flex items-center gap-2 text-lg font-semibold ${light ? "text-white" : "text-ink-900"}`}>
      <ShieldCheck className="h-5 w-5 text-brand" aria-hidden /> GuardRail
    </span>
  );
}
