"use client";

import Link from "next/link";
import { useJsonItemDismissed } from "@/lib/dismissed";

/**
 * The lede: what this is, in two sentences, as prose.
 *
 * It used to be a bordered, filled card, which gave an explanation the same
 * visual construction as the recommendations it was explaining — a first-time
 * reader could not tell which block was the product. Losing the border costs
 * nothing and stops it competing.
 */
export function LandingExplainer() {
  const { dismissed, dismiss, ready } = useJsonItemDismissed("explainer");

  // Rendered during SSR and until storage is read, so a first-time visitor sees
  // it in the initial HTML rather than after a flash.
  if (ready && dismissed) return null;

  return (
    <section className="relative max-w-[64ch]">
      <h1 className="prose text-lede font-semibold text-text">
        Two places price the same games.
        <br />
        <span className="text-dim">They don’t always agree.</span>
      </h1>
      <p className="prose mt-3 text-body text-muted">
        Arbitrium compares <span className="text-dim">Kalshi</span>, where the price is what
        traders will pay, against the <span className="text-dim">median of the sportsbooks</span>,
        with their margin stripped out. When they disagree by more than it costs to act, that’s a
        recommendation. When they don’t — or too few books have posted a line to judge — it says so
        instead of filling the space.
      </p>
      <p className="prose mt-2.5 text-meta text-faint">
        Every figure is gross of fees.{" "}
        <Link href="/how-it-works" className="tap text-signal-600 hover:text-signal">
          How this works →
        </Link>
        {ready ? (
          <>
            {" · "}
            <button
              type="button"
              onClick={dismiss}
              className="tap text-faint underline decoration-dotted underline-offset-2 hover:text-muted"
            >
              Dismiss
            </button>
          </>
        ) : null}
      </p>
    </section>
  );
}
