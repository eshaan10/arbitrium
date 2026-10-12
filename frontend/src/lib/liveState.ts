import type { Live } from "./types";

export type GameState = "scheduled" | "live" | "started" | "final";

export function gameState(
  d: { scheduled_start: string; live: Live | null },
  now: Date = new Date(),
): GameState {
  const s = d.live?.status;
  if (s === "in_progress" || s === "halftime") return "live";
  if (s === "final") return "final";
  const start = new Date(d.scheduled_start).getTime();
  if (!Number.isNaN(start) && now.getTime() > start) return "started";
  return "scheduled";
}

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
  const rem = min - hr * 60;
  return rem > 0 ? `starts in ${hr}h ${rem}m` : `starts in ${hr}h`;
}
