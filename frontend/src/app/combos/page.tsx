import { TierSelector } from "@/components/combos/TierSelector";
import { ComboShapePreview } from "@/components/combos/ComboShapePreview";
import { Card, SectionHeading } from "@/components/primitives";
import type { RiskTier } from "@/lib/types";

export const dynamic = "force-dynamic";

function parseTier(v: string | string[] | undefined): RiskTier {
  return v === "safe" || v === "max_payout" ? v : "balanced";
}

const TIER_COPY: Record<RiskTier, string> = {
  safe: "Fewer legs, higher individual probabilities. The joint probability stays high and the payout stays small.",
  balanced: "A middle tier. Neither the highest chance of paying nor the largest payout.",
  max_payout:
    "More legs, longer odds. The payout is the largest and the chance of collecting it is the smallest.",
};

export default async function CombosPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const tier = parseTier(sp.tier);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lede font-semibold">Combo builder</h1>
        <p className="prose mt-1.5 max-w-prose text-body leading-relaxed text-dim">
          Multi-leg positions ranked within an explicit risk tier. &ldquo;Safe&rdquo; and
          &ldquo;max payout&rdquo; are different axes and no combo is ever claimed to be both — the
          tier is a choice you make, not an optimum the system finds for you.
        </p>
      </div>

      {/* The optimizer is Phase 4 and has no endpoint yet. Saying so plainly
          beats a spinner that never resolves or a demo that reads as live. */}
      <div className="rounded-md border border-warn/40 bg-[color-mix(in_srgb,var(--warn)_8%,transparent)] p-4">
        <h2 className="text-body font-medium text-warn">Not live yet</h2>
        <p className="prose mt-1.5 max-w-prose text-meta leading-relaxed text-dim">
          The combo optimizer ships in Phase 4. There is no <code>/combos</code> endpoint to call
          yet, so nothing below is a recommendation — the controls and the card layout are here so
          the shape can be reviewed before the numbers exist. Joint probabilities depend on
          calibrated per-leg probabilities, which Phase 3 is still producing.
        </p>
      </div>

      <div>
        <SectionHeading note="Pick the axis you care about. The optimizer will rank within the tier, never across tiers.">
          Risk tier
        </SectionHeading>
        <TierSelector tier={tier} />
        <p className="prose mt-2.5 max-w-prose text-meta leading-relaxed text-muted">
          {TIER_COPY[tier]}
        </p>
      </div>

      <div>
        <SectionHeading>Card shape</SectionHeading>
        <ComboShapePreview tier={tier} />
      </div>

      <Card className="p-4">
        <h3 className="label text-meta font-semibold text-dim">
          What every combo will have to state
        </h3>
        <ul className="prose mt-2.5 space-y-2 text-meta leading-relaxed text-muted">
          <li>
            <span className="text-dim">Independence assumption.</span> Multiplying per-leg
            probabilities assumes the legs are independent. Two games in the same division on the
            same weekend are not, and any combo that multiplies through will say so on its face.
          </li>
          <li>
            <span className="text-dim">Which probability was used.</span> The calibrated one, with
            the sample size it rests on — not the raw model output.
          </li>
          <li>
            <span className="text-dim">Cost and payout, separately.</span> Never a single blended
            number, for the same reason the stake simulator shows both outcomes.
          </li>
        </ul>
      </Card>
    </div>
  );
}
