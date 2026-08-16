"use client";

import { useEffect, useRef } from "react";
import type { Divergence } from "./types";

/**
 * Flashes the cards whose price actually moved on the most recent poll.
 *
 * The signature is built from the EXECUTABLE Kalshi book (bid/ask per outcome),
 * because that is what a reader would act on — a shift in the consensus median
 * with an unchanged Kalshi book does not alter what you can buy. Two honest
 * consequences, both intended:
 *
 *  - Nothing flashes on first load. There is no previous poll to compare
 *    against, and inventing one would make the very first render lie.
 *  - A flash always means a real move. The backend's dedup trigger only stores
 *    genuine price changes, so a re-poll that observed identical prices cannot
 *    trigger this.
 *
 * The class is applied to the DOM directly rather than held in React state:
 * this is a transient, self-terminating CSS animation on an element React does
 * not otherwise re-render, which is precisely the "synchronise with an external
 * system" case effects exist for. Routing it through state would re-render
 * every card twice per poll to paint something CSS finishes on its own.
 */
const FLASH_CLASS = "animate-price-flash";

function signature(d: Divergence): string {
  return d.outcomes.map((o) => `${o.kalshi_bid ?? "-"}/${o.kalshi_ask ?? "-"}`).join("|");
}

export function usePriceFlash(events: Divergence[], updatedAt: number | undefined) {
  const previous = useRef<Map<string, string> | null>(null);

  useEffect(() => {
    const current = new Map(events.map((e) => [e.event_id, signature(e)]));
    const before = previous.current;
    previous.current = current;

    // First poll establishes the baseline and flashes nothing.
    if (!before) return;

    for (const [id, sig] of current) {
      const was = before.get(id);
      if (was == null || was === sig) continue;

      const el = document.querySelector<HTMLElement>(`[data-event-id="${CSS.escape(id)}"]`);
      if (!el) continue;

      // Remove, force a reflow, re-add: without this an element that flashed on
      // a previous poll would not replay the animation.
      el.classList.remove(FLASH_CLASS);
      void el.offsetWidth;
      el.classList.add(FLASH_CLASS);
    }
    // Keyed on the poll, not on the array: react-query hands back a new array
    // identity on every render, which would re-run this constantly and compare
    // each poll against itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updatedAt]);
}
