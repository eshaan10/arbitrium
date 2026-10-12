import { cents, fairValueCents } from "./format";
import { teamVisual } from "./teams";
import type { FinalGame, Live } from "./types";

/** Finished games shown before "Show N more" in "In progress or past". */
export const FINALS_SHOWN = 10;

export function capFinals<T>(
  finals: T[],
  expanded: boolean,
  cap: number = FINALS_SHOWN,
): { shown: T[]; more: number } {
  const more = Math.max(0, finals.length - cap);
  return { shown: expanded || more === 0 ? finals : finals.slice(0, cap), more };
}

function short(team: string | null): string {
  return teamVisual(team)?.short ?? team ?? "";
}

/** "Ravens to lose": the pick as it was flagged, or null when there was none. */
export function pickHeadline(f: FinalGame): string | null {
  if (!f.flagged) return null;
  return `${short(f.flagged.team)} to ${f.flagged.side === "yes" ? "win" : "lose"}`;
}

/** "Final · 15–23", away first to match "Ravens @ Falcons". */
export function finalScoreLine(f: FinalGame): string {
  return `Final · ${f.away_score}–${f.home_score}`;
}

/** "Falcons won" / "Tie": the headline of a game with no pick. */
export function winnerLine(f: FinalGame): string {
  return f.winner_team ? `${short(f.winner_team)} won` : "Tie";
}

/**
 * "We said: Ravens to lose at 54¢ (books 61¢). Result: Ravens lost 15-23. Pick hit."
 *
 * The result is told from the picked team's side, its own score first. The
 * verdict sentence is dropped when pick_result is null (a tie, or a call whose
 * side was never recorded), never guessed.
 */
export function weSaid(f: FinalGame): string | null {
  const headline = pickHeadline(f);
  if (!f.flagged || !headline) return null;
  const isHome = f.flagged.team === f.home_team;
  const mine = isHome ? f.home_score : f.away_score;
  const theirs = isHome ? f.away_score : f.home_score;
  const outcome = mine > theirs ? "won" : mine < theirs ? "lost" : "tied";
  const verdict =
    f.pick_result === "hit" ? " Pick hit." : f.pick_result === "miss" ? " Pick missed." : "";
  return (
    `We said: ${headline} at ${cents(f.flagged.price)} (books ${fairValueCents(f.flagged.fair_value, f.flagged.price)}). ` +
    `Result: ${short(f.flagged.team)} ${outcome} ${mine}-${theirs}.${verdict}`
  );
}

/**
 * The live object the final scoreboard renders from. ESPN's row when there is
 * one (it carries the linescore), always with the resolved score and status, so
 * a game resolved without a scoreboard row still shows its final.
 */
export function finalLive(f: FinalGame): Live {
  const base: Live = f.live ?? {
    status: "final",
    period: null,
    clock: null,
    detail: null,
    home_score: null,
    away_score: null,
    home_record: null,
    away_record: null,
    venue: null,
    broadcast: null,
    possession_side: null,
    down_distance: null,
    last_play: null,
    linescore: null,
    updated_at: f.scheduled_start,
  };
  return { ...base, status: "final", home_score: f.home_score, away_score: f.away_score };
}
