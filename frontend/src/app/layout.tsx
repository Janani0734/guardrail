import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@/styles/globals.css";
import { Providers } from "@/app/providers";

export const metadata: Metadata = {
  title: { default: "GuardRail — approval gateway for AI agents", template: "%s · GuardRail" },
  description: "Decide what your AI agents may do before they do it: allow, block, or ask a human.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
