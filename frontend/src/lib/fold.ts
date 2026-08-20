import type { View } from "@/components/dashboard/Controls";
import type { Divergence } from "./types";

/**
 * Below this, folding costs more than it saves: a disclosure control is itself
 * a row, so hiding one or two cards behind one is a net loss.
 */
export const FOLD_THRESHOLD = 3;

/**
 * Should unscoreable events be folded away in this view?
 *
 * Each exclusion is a case where folding would make the app look broken rather
 * than tidy, so they are enumerated here and pinned by tests:
 *
 *  - the "Can't score" view IS the unscoreable list;
 *  - a search must surface every match, or it reads as a failed search;
 *  - My Teams / My Games are short, hand-picked lists, and burying a followed
 *    team's game behind a disclosure defeats the point of following it.
 */
export function shouldFold(view: View, search: string): boolean {
  if (search.trim() !== "") return false;
  return view !== "unscoreable" && view !== "my-teams" && view !== "my-games";
}

/**
 * Split a date group into what stays as cards and what folds away.
 *
 * Only genuinely UNSCOREABLE events fold. A scored event with no edge right now
 * stays a card: "we compared these and found nothing" is a different statement
 * from "we could not compare these", and the first one is a real reading that
 * the reader came for.
 */
export function splitFoldable(
  events: Divergence[],
  enabled: boolean,
): [shown: Divergence[], folded: Divergence[]] {
  if (!enabled) return [events, []];
  const folded = events.filter((d) => d.status !== "scored");
  if (folded.length < FOLD_THRESHOLD) return [events, []];
  return [events.filter((d) => d.status === "scored"), folded];
}
