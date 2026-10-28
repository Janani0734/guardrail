import { cn } from "@/lib/utils";

const styles: Record<string, string> = {
  ALLOW: "bg-allow-bg text-allow-fg", ALLOWED: "bg-allow-bg text-allow-fg", APPROVED: "bg-allow-bg text-allow-fg", ACTIVE: "bg-allow-bg text-allow-fg",
  SUCCEEDED: "bg-allow-bg text-allow-fg",
  BLOCK: "bg-block-bg text-block-fg", BLOCKED: "bg-block-bg text-block-fg", REJECTED: "bg-block-bg text-block-fg", FAILED: "bg-block-bg text-block-fg",
  CRITICAL: "bg-block-bg text-block-fg", HIGH: "bg-review-bg text-review-fg",
  REQUIRE_APPROVAL: "bg-review-bg text-review-fg", PENDING: "bg-review-bg text-review-fg", PENDING_APPROVAL: "bg-review-bg text-review-fg", MEDIUM: "bg-review-bg text-review-fg",
  EXPIRED: "bg-expired-bg text-expired-fg", DISABLED: "bg-expired-bg text-expired-fg", LOW: "bg-expired-bg text-expired-fg", REVOKED: "bg-expired-bg text-expired-fg",
};

export function StatusBadge({ value, className }: { value: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center whitespace-nowrap rounded px-2 py-0.5 text-xs font-semibold", styles[value] ?? "bg-expired-bg text-expired-fg", className)}>
      {value.replace(/_/g, " ")}
    </span>
  );
}

export function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return <code className={cn("rounded bg-paper px-1.5 py-0.5 font-mono text-xs text-ink-800", className)}>{children}</code>;
}
