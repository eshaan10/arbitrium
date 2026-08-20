import { money } from "@/lib/format";
import { teamVisual } from "@/lib/teams";
import type { Divergence } from "@/lib/types";

/**
 * Cross-platform arbitrage — a SEPARATE product, fenced off deliberately.
 *
 * This is the only place in the app allowed to use guaranteed-payout language,
 * and the only place a single number describes a return, because this is the
 * only trade where the payout does not depend on who wins. It never appears as
 * a card headline; a reader who confuses it with the directional
 * recommendation would badly misjudge the risk of the latter.
 */
export function ArbitragePanel({ d }: { d: Divergence }) {
  const a = d.arbitrage;
  if (!d.is_arbitrage || !a) return null;

  const others = a.venues.filter((v) => v !== "kalshi");
  const stake = 100;
  const profit = a.total_cost > 0 ? stake * (1 / a.total_cost - 1) : 0;

  return (
    <section className="rounded-md border border-arb bg-[var(--arb-glow)] p-3.5 sm:p-4">
      <h3 className="label text-meta font-semibold text-arb">
        Cross-platform opportunity — a separate product
      </h3>

      <p className="prose mt-2 text-meta leading-relaxed text-dim">
        {a.includes_kalshi ? (
          <>
            Requires a Kalshi account <strong className="text-text">and</strong> an account at{" "}
            {others.join(", ")}.
          </>
        ) : (
          <span className="text-warn">
            Requires accounts at {others.join(" and ")} — <strong>no Kalshi leg</strong>. This one
            cannot be taken on Kalshi at all.
          </span>
        )}
      </p>

      <p className="prose mt-2 max-w-prose text-meta leading-relaxed text-dim">
        Unlike the recommendation above, this covers <em>every</em> outcome, so the payout does not
        depend on who wins. Both legs must fill at these prices, and the figure is gross — before
        fees and execution risk.
      </p>

      {/* Three narrow columns, so this one genuinely does fit a phone — the
          team name is abbreviated below `sm` rather than the table being
          scrolled, because the outcome is the column you cannot afford to push
          off-screen. No min-width: it would create a scroll that isn't needed. */}
      <div className="scroll-x mt-3">
        <table className="w-full border-collapse text-meta">
          <thead>
            <tr className="border-b border-[color-mix(in_srgb,var(--arb)_30%,transparent)] text-left">
              <th className="label py-2 pr-3 text-micro font-medium text-muted">Outcome</th>
              <th className="label py-2 pr-3 text-micro font-medium text-muted">Venue</th>
              <th className="label py-2 text-micro font-medium text-muted">Cost</th>
            </tr>
          </thead>
          <tbody>
            {a.legs.map((leg, i) => (
              <tr key={`${leg.venue}-${leg.team}-${i}`} className="border-b border-[var(--border)]">
                <td className="py-1.5 pr-3 text-dim">
                  <span className="sm:hidden">{teamVisual(leg.team)?.short ?? leg.team}</span>
                  <span className="hidden sm:inline">{leg.team}</span>
                </td>
                <td className="py-1.5 pr-3 text-dim">{leg.venue}</td>
                <td className="tabular py-1.5 text-text">
                  {(leg.implied_price * 100).toFixed(2)}¢
                </td>
              </tr>
            ))}
            <tr>
              <td colSpan={2} className="py-2 pr-3 font-medium text-dim">
                Total for $1 payout
              </td>
              <td className="tabular py-2 font-semibold text-arb">
                {(a.total_cost * 100).toFixed(2)}¢
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-meta text-muted">
        Splitting ${stake} across both legs returns about{" "}
        <strong className="tabular text-arb">{money(profit)}</strong> gross, whoever wins.
        {a.limiting_depth != null ? (
          <> Limited by {a.limiting_depth.toLocaleString()} contracts on the thinner leg.</>
        ) : null}
      </p>
    </section>
  );
}
