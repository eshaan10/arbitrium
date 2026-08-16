"use client";

import { useEffect, useRef } from "react";
import { useRecentlyViewed } from "@/lib/storage";

/**
 * Records this event in the browser's recently-viewed list.
 *
 * Lives on the detail page rather than only in the card's click handler so a
 * deep link, a back-forward navigation, or a link shared into the browser all
 * count as a visit — the card handler alone would only ever see visits that
 * started on the dashboard.
 */
export function RecordView({
  id,
  home,
  away,
  sport,
  rec,
  arb,
}: {
  id: string;
  home: string | null;
  away: string | null;
  sport: string | null;
  /** Recommendation signature at the moment of this visit — the baseline for
   *  "what changed since your last visit". */
  rec: string | null;
  arb: boolean;
}) {
  const { record } = useRecentlyViewed();
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    record({ id, home, away, sport, rec, arb });
  }, [id, home, away, sport, rec, arb, record]);

  return null;
}
