import type { Metadata, Viewport } from "next";
import { JetBrains_Mono } from "next/font/google";
import { AppShell } from "@/components/layout/AppShell";
import { Providers } from "./providers";
import "./globals.css";

/**
 * One webfont, for the whole app.
 *
 * The terminal identity is carried by how everything is typeset — the
 * measurements and the sentences that explain them — so this face is worth a
 * download and there is no second one. `display: "swap"` because a dashboard
 * that shows nothing while a font loads is worse than one that reflows.
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
