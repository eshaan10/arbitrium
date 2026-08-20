import type { Metadata, Viewport } from "next";
import { JetBrains_Mono } from "next/font/google";
import { AppShell } from "@/components/layout/AppShell";
import { Providers } from "./providers";
import "./globals.css";

/**
 * One webfont, for the data only.
 *
 * The terminal identity is carried by how the measurements are typeset, so the
 * mono is worth a download; prose stays on the system sans, which costs
 * nothing and is what the reader's own OS renders best. `display: "swap"`
 * because a dashboard that shows nothing while a font loads is worse than one
 * that reflows.
 */
const data = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-data",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Arbitrium",
  description:
    "Kalshi versus sportsbook consensus — divergences, what is actually capturable, and an honest record of how often it was right.",
};

/**
 * `maximumScale` is deliberately absent. Locking zoom would stop the layout
 * shifting on an input focus, but it takes pinch-zoom away from everyone who
 * needs it; the 16px input rule in globals.css fixes the same problem without
 * the cost.
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0b0a09",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={data.variable}>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
