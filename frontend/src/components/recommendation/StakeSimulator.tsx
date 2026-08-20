"use client";

import { useState } from "react";
import { money, num } from "@/lib/format";
import { AnimatedNumber } from "@/components/primitives/AnimatedNumber";
import type { Recommendation } from "@/lib/types";

/**
 * Stake simulator for a DIRECTIONAL bet.
 *
 * Both outcomes are ALWAYS shown, side by side, collapsed or not. A single
 * blended expected-value number would read as a promise, and this trade makes
 * no promise — it pays $1 or it pays nothing. The one guaranteed figure in this
 * product belongs to true arbitrage and lives only in the arbitrage panel.
 *
 * Collapsed by default. It used to render as a filled, bordered box on every
 * card, which gave a calculator the same weight as the recommendation it was
 * calculating. The default $100 result stays visible as one quiet line; the
 * input appears when someone actually wants to change the number.
 */
export function StakeSimulator({ rec }: { rec: Recommendation }) {
  const [stake, setStake] = useState(100);
  const [open, setOpen] = useState(false);

  // Contracts are whole things — you cannot buy 572.76 of them — so the
  // simulator quotes what would actually fill, not a fractional ideal.
  const wanted = stake > 0 && rec.price > 0 ? Math.floor(stake / rec.price) : 0;
  const cap = rec.max_contracts == null ? null : Math.floor(rec.max_contracts);
  const capped = cap != null && wanted > cap;
  const usable = capped ? cap! : wanted;
  const spend = usable * rec.price;
  const ifWin = usable - spend;

  return (
    <div className="relative z-20">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-meta">
        {open ? (
          <span className="flex items-baseline gap-1.5">
            <label htmlFor={`stake-${rec.team}`} className="text-muted">
              Stake $
            </label>
            {/* `inputMode="numeric"` rather than "decimal": a stake is whole
                dollars here, and the numeric keypad is the one without a
                decimal point to mis-tap. globals.css raises it to 16px below
                `sm` so focusing it does not zoom the viewport — which on a
                card mid-list scrolled the card out from under the reader. */}
            <input
              id={`stake-${rec.team}`}
              type="number"
              min={1}
              step={10}
              inputMode="numeric"
              autoFocus
              value={stake}
              onChange={(e) => setStake(Math.max(0, Number(e.target.value)))}
              aria-label="Stake in dollars"
              className="tabular w-[72px] rounded-sm border border-border-lit bg-[var(--surface-sunken)] px-1.5 py-[3px] text-body text-text"
            />
          </span>
        ) : (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setOpen(true);
            }}
            className="tap tabular text-muted underline decoration-dotted underline-offset-2 hover:text-dim"
            title="Change the stake"
          >
            ${stake}
          </button>
        )}

        <span aria-hidden className="text-faint">
          →
        </span>

        <span className="flex items-baseline gap-1">
          <AnimatedNumber
            value={ifWin}
            format={(n) => `+${money(n)}`}
            className="tabular font-medium text-gain"
          />
          {/* Verbatim from the API. Trimming a trailing "wins" broke the 'no'
              side, whose wins_if reads "<team> loses" — producing "if Las Vegas
              Raiders loses wins". The backend already phrases this correctly. */}
          <span className="text-faint">if {rec.wins_if}</span>
        </span>

        <span aria-hidden className="text-faint">
          ·
        </span>

        <span className="flex items-baseline gap-1">
          <AnimatedNumber
            value={spend}
            format={(n) => `−${money(n)}`}
            className="tabular font-medium text-loss"
          />
          <span className="text-faint">if not</span>
        </span>
      </div>

      {capped ? (
        <p className="mt-1 text-micro text-warn">
          Only {num(cap)} contracts resting at this price ({money(rec.max_stake)} max) — more would
          move the market against you.
        </p>
      ) : null}
    </div>
  );
}
