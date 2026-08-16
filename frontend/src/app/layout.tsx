import type { Metadata } from "next";
import { AppShell } from "@/components/layout/AppShell";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Arbitrium",
  description:
    "Kalshi versus sportsbook consensus — divergences, what is actually capturable, and an honest record of how often it was right.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
