"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { DivergencesResponse } from "./types";

export interface LiveArbitrage {
  eventId: string;
  label: string;
  at: string;
}

/**
 * Arbitrage appearances observed while this page has been open.
 *
 * Arbitrage is computed on read by the divergence engine and never persisted,
 * so there is no history of when one opened — it cannot come from /activity
 * like price moves do. Detecting it across polls is the only honest source, and
 * it carries a real limitation the UI must state: it can only ever show what
 * appeared while you were watching, and it is empty on first load.
 *
 * Watches the divergences cache rather than issuing its own request, so it
 * costs nothing beyond what the dashboard already fetches.
 */
const MAX_KEPT = 3;

export function useLiveArbitrage(): LiveArbitrage[] {
  const client = useQueryClient();
  const known = useRef<Set<string> | null>(null);
  const [appeared, setAppeared] = useState<LiveArbitrage[]>([]);

  useEffect(() => {
    const read = () => {
      const entries = client.getQueriesData<DivergencesResponse>({ queryKey: ["divergences"] });
      const data = entries.find(([, v]) => v)?.[1];
      if (!data) return;

      const current = new Set(
        data.divergences.filter((d) => d.is_arbitrage).map((d) => d.event_id),
      );

      // First observation establishes the baseline: everything already open
      // when the page loaded is not something that "appeared".
      if (known.current === null) {
        known.current = current;
        return;
      }

      const fresh = data.divergences.filter(
        (d) => d.is_arbitrage && !known.current!.has(d.event_id),
      );
      known.current = current;
      if (fresh.length === 0) return;

      setAppeared((prev) =>
        [
          ...fresh.map((d) => ({
            eventId: d.event_id,
            label: `${d.away_team} @ ${d.home_team}`,
            at: new Date().toISOString(),
          })),
          ...prev,
        ].slice(0, MAX_KEPT),
      );
    };

    read();
    const unsubscribe = client.getQueryCache().subscribe(read);
    return unsubscribe;
  }, [client]);

  return appeared;
}
