"use client";

import { useId, useState, type SyntheticEvent } from "react";
import { num } from "@/lib/format";
import {
  DEFAULT_BET_CENTS,
  availableContracts,
  centsToField,
  formatCents,
  maxFillCents,
  parseBet,
  priceToCents,
  quoteStake,
  sliderSpec,
  stopIndexFor,
} from "@/lib/stake";
import type { Recommendation } from "@/lib/types";

/**
 * "Your bet": a typed amount, a slider linked to it, and BOTH outcomes.
 *
 * All the arithmetic lives in lib/stake.ts; this component only holds the text
 * the reader typed and renders what that module says it buys.
 *
 * Both outcomes are always shown, side by side or stacked. A single blended
 * expected-value number would read as a promise, and a directional bet makes
 * none: it pays $1 a contract or it pays nothing. Win and loss are told apart
 * by sign and by label, never by colour alone.
 *
 * The card behind this is one big link. Everything here sits above it (z-20)
 * and stops pointer events from bubbling, so typing, dragging and clicking in
 * the bet never navigate.
 */
const stop = (e: SyntheticEvent) => e.stopPropagation();

export function BetControls({ rec, teamShort }: { rec: Recommendation; teamShort: string }) {
  const priceCents = priceToCents(rec.price);
  const available = availableContracts(rec.max_contracts);
  const slider = sliderSpec(priceCents, available);
  const fill = maxFillCents(priceCents, available);

  const [field, setField] = useState(centsToField(DEFAULT_BET_CENTS));
  // The message appears when the reader commits a value (blur or Enter) and
  // goes away on their next keystroke, so it never shouts at a half-typed
  // "0." — but the results below go to dashes immediately either way.
  const [showError, setShowError] = useState(false);

  const id = useId();
  const parsed = parseBet(field, priceCents);
  // Nothing resting at this price at all (the API reports fractions like 0.02,
  // which floor to zero). Quoting "+$0.00 / −$0.00, 0 contracts" would look
  // like a result; it is the absence of one, so the outcomes go to dashes.
  const noDepth = available === 0;
  const quote =
    parsed.ok && !noDepth ? quoteStake(parsed.cents, priceCents, available) : null;

  const message = !parsed.ok
    ? parsed.error === "below-one-contract"
      ? `You need at least ${formatCents(priceCents)} to buy one contract`
      : "Enter an amount above $0"
    : null;

  const index = slider.show ? stopIndexFor(slider.stops, parsed.ok ? parsed.cents : 0) : 0;
  const lastIndex = slider.show ? slider.stops.length - 1 : 0;
  const fillPct = lastIndex > 0 ? (index / lastIndex) * 100 : 100;

  const yes = rec.side === "yes";
  const winWhen = `If ${teamShort} ${yes ? "win" : "lose"}`;
  const loseWhen = `If ${teamShort} ${yes ? "lose" : "win"}`;
  const dash = "—";

  return (
    <div className="relative z-20" onClick={stop} onPointerDown={stop}>
      <label htmlFor={`${id}-bet`} className="block text-[13px] font-medium text-muted">
        Your bet
      </label>

      <div
        className="mt-1.5 flex h-[50px] w-full items-center gap-1 rounded-lg border border-border-input bg-raised px-3.5 transition-colors focus-within:border-signal"
      >
        <span aria-hidden className="display bet-dollar text-signal">
          $
        </span>
        <input
          id={`${id}-bet`}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          spellCheck={false}
          value={field}
          onChange={(e) => {
            setField(e.target.value);
            setShowError(false);
          }}
          onBlur={() => setShowError(!parsed.ok)}
          onKeyDown={(e) => {
            if (e.key === "Enter") setShowError(!parsed.ok);
          }}
          aria-label="Your bet in dollars"
          aria-invalid={showError && !parsed.ok}
          aria-describedby={`${id}-msg ${id}-summary`}
          className="display bet-amount tabular h-full min-w-0 flex-1 bg-transparent text-signal outline-none placeholder:text-faint"
          placeholder="0"
        />
      </div>

      <p id={`${id}-msg`} role="status" className="min-h-0 text-[13px] text-error">
        {showError && message ? <span className="mt-1.5 block">{message}</span> : null}
      </p>

      {slider.show ? (
        <input
          type="range"
          min={0}
          max={lastIndex}
          step={1}
          value={index}
          disabled={lastIndex === 0}
          onChange={(e) => {
            setField(centsToField(slider.stops[Number(e.target.value)]));
            setShowError(false);
          }}
          aria-label="Bet amount"
          aria-valuetext={formatCents(slider.stops[index])}
          style={{ ["--fill" as string]: `${fillPct}%` }}
          className="bet-slider w-full"
        />
      ) : (
        <p className="mt-1.5 text-[13px] text-warn">
          {noDepth ? (
            <>
              No contracts are resting at {priceCents}¢ right now, so this bet can&apos;t be
              placed at this price.
            </>
          ) : (
            <>
              Only {formatCents(fill ?? 0)} is available at {priceCents}¢ ({num(available)}{" "}
              {available === 1 ? "contract" : "contracts"}), so this bet can&apos;t go higher.
            </>
          )}
        </p>
      )}

      <div className="outcome-tiles mt-3">
        <div className="outcome-tile rounded-lg bg-raised px-3 py-2.5">
          <div className="text-[13px] text-muted">{winWhen}, you win</div>
          <div className="display outcome-figure tabular mt-1 text-gain">
            {quote ? `+${formatCents(quote.winCents)}` : dash}
          </div>
        </div>
        <div className="outcome-tile rounded-lg bg-raised px-3 py-2.5">
          <div className="text-[13px] text-muted">{loseWhen}, you lose</div>
          <div className="display outcome-figure tabular mt-1 text-loss">
            {quote ? `−${formatCents(quote.costCents)}` : dash}
          </div>
        </div>
      </div>

      <p id={`${id}-summary`} className="tabular mt-2.5 text-[13px] text-faint">
        {quote
          ? `${num(quote.contracts)} ${quote.contracts === 1 ? "contract" : "contracts"} · ${formatCents(
              quote.costCents,
            )} in play, before fees`
          : `${dash} contracts · ${dash} in play, before fees`}
      </p>

      {quote?.capped && fill != null ? (
        <p className="mt-1 text-[13px] text-warn">
          Only {num(available)} contracts are resting at {priceCents}¢, so the most this bet can use
          is {formatCents(fill)}. More would move the price against you.
        </p>
      ) : null}
    </div>
  );
}
