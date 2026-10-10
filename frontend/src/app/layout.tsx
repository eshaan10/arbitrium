import type { Metadata, Viewport } from "next";
import { Inter, Unbounded } from "next/font/google";
import { AppShell } from "@/components/layout/AppShell";
import { Providers } from "./providers";
import "./globals.css";

/**
 * Two faces, both bundled by next/font at build time and served from this
 * origin — the browser never requests anything from Google.
 *
 * Inter is the face for everything. Unbounded is the display face, opted into
 * with `.display` for the handful of things a glance should land on, and only
 * in the two weights loaded here. `display: "swap"` because a dashboard that
 * shows nothing while a font loads is worse than one that reflows.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const unbounded = Unbounded({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-unbounded",
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
  themeColor: "#0a0b0d",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning on <html> and <body> ONLY: browser extensions
    // (Grammarly adds data-gr-ext-installed and data-new-gr-c-s-check-loaded)
    // write attributes onto these two tags before React hydrates. It applies
    // to these elements' own attributes, one level deep — a real mismatch
    // anywhere inside the page is still reported.
    <html
      lang="en"
      className={`${inter.variable} ${unbounded.variable}`}
      suppressHydrationWarning
    >
      <body suppressHydrationWarning>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
