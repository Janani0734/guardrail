import Link from "next/link";
import type { ReactNode } from "react";
import { Logo } from "@/components/layout/logo";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-10">
      <Link href="/" className="mb-6"><Logo /></Link>
      <div className="w-full max-w-sm rounded-lg border border-line bg-white p-6 shadow-sm">{children}</div>
    </main>
  );
}
