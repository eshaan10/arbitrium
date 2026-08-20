"use client";

import { useRouter } from "next/navigation";
import type { RiskTier } from "@/lib/types";

const TIERS: { key: RiskTier; label: string }[] = [
  { key: "safe", label: "Safe" },
  { key: "balanced", label: "Balanced" },
  { key: "max_payout", label: "Max payout" },
];

/**
 * An explicit tier choice, not a hidden optimum.
 *
 * The three tiers are presented as equals — no "recommended" badge, no default
 * highlighted as best — because the product's position is that safety and
 * payout are different axes and the user picks which one they are buying.
 */
export function TierSelector({ tier }: { tier: RiskTier }) {
  const router = useRouter();

  return (
    <div className="inline-flex rounded-sm border border-border p-0.5" role="group">
      {TIERS.map((t) => (
        <button
          key={t.key}
          aria-pressed={tier === t.key}
          onClick={() => {
            const params = new URLSearchParams(window.location.search);
            params.set("tier", t.key);
            router.replace(`${window.location.pathname}?${params}`, { scroll: false });
          }}
          className={`tap rounded-[3px] px-3 py-1.5 text-meta transition-colors ${
            tier === t.key ? "bg-raised text-text" : "text-muted hover:text-dim"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
