import type { Live } from "./types";

export type GameState = "scheduled" | "live" | "started" | "final";

/**
 * How long after kickoff an in-progress row may still read as LIVE. Matches
 * the backend's MAX_GAME_DURATION, past which it stops polling the game: a row
 * ESPN never updated again is stale by then, and shows as "Started" rather
 * than a LIVE dot that would never go out.
 */
export const LIVE_MAX_AGE_MS = 6 * 60 * 60 * 1000;

export function gameState(
  d: { scheduled_start: string; live: Live | null },
  now: Date = new Date(),
): GameState {
  const s = d.live?.status;
  const start = new Date(d.scheduled_start).getTime();
  const fresh = Number.isNaN(start) || now.getTime() - start <= LIVE_MAX_AGE_MS;
  if ((s === "in_progress" || s === "halftime") && fresh) return "live";
  if (s === "final") return "final";
  if (!Number.isNaN(start) && now.getTime() > start) return "started";
  return "scheduled";
}

/**
 * Whether a game gets a scoreboard: always before kickoff, from the event's own
 * teams and start time when ESPN has not written a row yet, and afterwards only
 * when there is live state to show. A past game with no row stays blank rather
 * than showing an empty "Started" board.
 */
export function hasScoreboard(
  d: { scheduled_start: string; live: Live | null },
  now: Date = new Date(),
): boolean {
  return d.live != null || gameState(d, now) === "scheduled";
}

/**
 * The game is under way by ESPN's last word, however old. Gates price logic
 * (in-game Kalshi prices are not pregame edges), not the LIVE display: that is
 * gameState, which also requires the row to be fresh.
 */
export function isLive(d: { live: Live | null }): boolean {
  const s = d.live?.status;
  return s === "in_progress" || s === "halftime";
}

export function countdownTo(start: string, now: Date = new Date()): string {
  const target = new Date(start).getTime();
  if (Number.isNaN(target)) return "";
  const diffMs = target - now.getTime();
  if (diffMs <= 0) return "";
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `starts in ${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `starts in ${min}m`;
  const hr = Math.floor(min / 60);
  if (hr >= 24) {
    const days = Math.floor(hr / 24);
    const hrs = hr - days * 24;
    return hrs > 0 ? `starts in ${days}d ${hrs}h` : `starts in ${days}d`;
  }
  const rem = min - hr * 60;
  return rem > 0 ? `starts in ${hr}h ${rem}m` : `starts in ${hr}h`;
}
