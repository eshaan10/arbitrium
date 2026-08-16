import type { Divergence } from "./types";
import type { RecentEvent } from "./storage";

/**
 * What the recommendation was, compressed to a comparable string.
 *
 * Side and team only — NOT price. A price ticking one cent is not "your
 * recommendation changed", and treating it as one would make the since-last-
 * visit indicator fire constantly and mean nothing.
 */
export function recSignature(d: Divergence): string | null {
  return d.recommendation ? `${d.recommendation.side}|${d.recommendation.team}` : null;
}

export type ChangeKind = "flipped" | "appeared" | "disappeared" | "arbitrage";

export interface SinceLastVisitChange {
  eventId: string;
  label: string;
  kind: ChangeKind;
  detail: string;
}

const KIND_DETAIL: Record<ChangeKind, string> = {
  flipped: "the recommended side changed since you looked",
  appeared: "now has a recommendation it did not have",
  disappeared: "no longer has a recommendation",
  arbitrage: "an arbitrage has opened since you looked",
};

/**
 * Compares what you saw against what is true now.
 *
 * Only events you actually opened are considered, and only against a baseline
 * that was genuinely recorded — an entry without a stored snapshot is skipped
 * rather than reported as unchanged or as new.
 */
export function changesSinceLastVisit(
  recent: RecentEvent[],
  live: Divergence[],
): SinceLastVisitChange[] {
  const byId = new Map(live.map((d) => [d.event_id, d]));
  const out: SinceLastVisitChange[] = [];

  for (const seen of recent) {
    const now = byId.get(seen.id);
    if (!now) continue; // dropped out of the feed; nothing honest to say
    // Written by an older schema version, so there is no baseline to compare.
    if (!("rec" in seen)) continue;

    const label = `${seen.away ?? now.away_team} @ ${seen.home ?? now.home_team}`;
    const nowSig = recSignature(now);

    let kind: ChangeKind | null = null;
    if (seen.rec && nowSig && seen.rec !== nowSig) kind = "flipped";
    else if (!seen.rec && nowSig) kind = "appeared";
    else if (seen.rec && !nowSig) kind = "disappeared";

    if (kind) {
      out.push({ eventId: seen.id, label, kind, detail: KIND_DETAIL[kind] });
      continue;
    }

    if (!seen.arb && now.is_arbitrage) {
      out.push({
        eventId: seen.id,
        label,
        kind: "arbitrage",
        detail: KIND_DETAIL.arbitrage,
      });
    }
  }

  return out;
}
