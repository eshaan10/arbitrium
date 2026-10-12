"use client";

import { useEffect, useState } from "react";
import { KickoffTime } from "./KickoffTime";
import { TeamLogo } from "./Matchup";
import { matchupVisuals, teamInitials, teamVisual } from "@/lib/teams";
import { countdownTo, gameState } from "@/lib/liveState";
import type { Live, PickResult } from "@/lib/types";

interface ScoreboardProps {
  home_team: string | null;
  away_team: string | null;
  scheduled_start: string;
  sport: string | null;
  live: Live | null;
  pick_result?: PickResult;
}

function LiveDot({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-2 w-2 rounded-full bg-[var(--live)] motion-safe:animate-pulse ${className}`}
    />
  );
}

function Side({
  name,
  short,
  visual,
  accent,
  record,
  possession,
}: {
  name: string | null;
  short: string;
  visual: ReturnType<typeof teamVisual>;
  accent: string;
  record: string | null;
  possession: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col items-center gap-1">
      <TeamLogo visual={visual} name={name} accent={accent} size={44} cutout="var(--surface)" />
      <div className="flex items-center gap-1 text-[13px] font-medium text-text">
        <span className="truncate">{short}</span>
        {possession ? <LiveDot className="h-1.5 w-1.5" /> : null}
      </div>
      {record ? <div className="tabular text-micro text-faint">{record}</div> : null}
    </div>
  );
}

/** "BAL", from the registry's ESPN abbreviation; initials for an unknown team. */
function abbreviation(name: string | null): string {
  return (teamVisual(name)?.abbr ?? teamInitials(name)).toUpperCase();
}

/** The total column is ruled off from the periods so it never reads as one more. */
const TOTAL_CELL = "border-l border-border pl-3 pr-1 text-right";

function Linescore({
  linescore,
  labels,
}: {
  linescore: { home: number[]; away: number[] };
  labels: { home: string; away: string };
}) {
  const periods = Math.max(linescore.home.length, linescore.away.length);
  if (periods === 0) return null;
  const cols = Array.from({ length: periods }, (_, i) => i);
  const rows = [
    { side: "away" as const, label: labels.away, scores: linescore.away },
    { side: "home" as const, label: labels.home, scores: linescore.home },
  ];
  return (
    <table className="tabular mt-3 w-full border-t border-border text-micro">
      <thead>
        <tr className="text-faint">
          <th className="pt-3 text-left font-normal"></th>
          {cols.map((i) => (
            <th key={i} className="px-1 pt-3 text-center font-normal">
              {i + 1}
            </th>
          ))}
          <th className={`${TOTAL_CELL} pt-3 font-medium text-dim`}>T</th>
        </tr>
      </thead>
      <tbody className="text-muted">
        {rows.map(({ side, label, scores }) => (
          <tr key={side}>
            <td className="text-left font-medium text-dim">{label}</td>
            {cols.map((i) => (
              <td key={i} className="px-1 text-center">
                {scores[i] ?? "-"}
              </td>
            ))}
            <td className={`${TOTAL_CELL} font-medium text-text`}>
              {scores.reduce((a, b) => a + b, 0)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function useNow(enabled: boolean, intervalMs = 1000): Date {
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [enabled, intervalMs]);
  return now;
}

export function Scoreboard({
  home_team,
  away_team,
  scheduled_start,
  sport,
  live,
  pick_result,
}: ScoreboardProps) {
  const state = gameState({ scheduled_start, live });
  const now = useNow(state === "scheduled");
  const { home, away, homeAccent, awayAccent } = matchupVisuals(home_team, away_team);
  const homeShort = teamVisual(home_team)?.short ?? home_team ?? "Home";
  const awayShort = teamVisual(away_team)?.short ?? away_team ?? "Away";
  const labels = { home: abbreviation(home_team), away: abbreviation(away_team) };
  const sportKey = sport?.toLowerCase() ?? "";
  const showPossessionAndDowns = sportKey === "nfl" || sportKey === "ncaaf";

  const possessionHome = showPossessionAndDowns && live?.possession_side === "home";
  const possessionAway = showPossessionAndDowns && live?.possession_side === "away";

  return (
    <div>
      {state === "live" && live ? (
        <>
          <span className="inline-flex items-center gap-1.5 text-micro font-semibold text-[var(--live)]">
            <LiveDot />
            Live
          </span>
          <div className="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
            <Side
              name={away_team}
              short={awayShort}
              visual={away}
              accent={awayAccent}
              record={live.away_record}
              possession={possessionAway}
            />
            <div className="tabular text-center text-[32px] font-semibold leading-none text-text">
              {live.away_score ?? 0}
              <span className="mx-2 text-faint">-</span>
              {live.home_score ?? 0}
            </div>
            <Side
              name={home_team}
              short={homeShort}
              visual={home}
              accent={homeAccent}
              record={live.home_record}
              possession={possessionHome}
            />
          </div>
          <div className="mt-2 text-center text-micro text-dim">
            {live.detail ?? (live.status === "halftime" ? "Halftime" : "In progress")}
          </div>
          {showPossessionAndDowns && live.down_distance ? (
            <div className="mt-1 text-center text-micro text-muted">{live.down_distance}</div>
          ) : null}
          {live.last_play ? (
            <div className="mt-1 truncate text-center text-micro text-muted" title={live.last_play}>
              {live.last_play}
            </div>
          ) : null}
          {live.linescore ? <Linescore linescore={live.linescore} labels={labels} /> : null}
        </>
      ) : state === "final" && live ? (
        <>
          <span className="text-micro font-semibold text-muted">Final</span>
          <div className="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
            <Side
              name={away_team}
              short={awayShort}
              visual={away}
              accent={awayAccent}
              record={live.away_record}
              possession={false}
            />
            <div className="tabular text-center text-[32px] font-semibold leading-none text-text">
              {live.away_score ?? 0}
              <span className="mx-2 text-faint">-</span>
              {live.home_score ?? 0}
            </div>
            <Side
              name={home_team}
              short={homeShort}
              visual={home}
              accent={homeAccent}
              record={live.home_record}
              possession={false}
            />
          </div>
          <FinalPickLine
            homeShort={homeShort}
            awayShort={awayShort}
            homeScore={live.home_score}
            awayScore={live.away_score}
            pickResult={pick_result ?? null}
          />
          {live.linescore ? <Linescore linescore={live.linescore} labels={labels} /> : null}
        </>
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            <span className="text-micro font-semibold text-muted">
              {state === "started" ? "Started" : "Scheduled"}
            </span>
            <KickoffTime iso={scheduled_start} className="tabular text-micro text-faint" />
          </div>
          <div className="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
            <Side
              name={away_team}
              short={awayShort}
              visual={away}
              accent={awayAccent}
              record={live?.away_record ?? null}
              possession={false}
            />
            <div className="text-center text-faint">at</div>
            <Side
              name={home_team}
              short={homeShort}
              visual={home}
              accent={homeAccent}
              record={live?.home_record ?? null}
              possession={false}
            />
          </div>
          {state === "scheduled" ? (
            <div suppressHydrationWarning className="mt-2 text-center text-micro text-muted">
              {countdownTo(scheduled_start, now) || "Starting soon"}
            </div>
          ) : null}
          {live?.venue ? (
            <div className="mt-1 truncate text-center text-micro text-faint">{live.venue}</div>
          ) : null}
          {live?.broadcast ? (
            <div className="mt-1 truncate text-center text-micro text-faint">TV: {live.broadcast}</div>
          ) : null}
        </>
      )}
    </div>
  );
}

function FinalPickLine({
  homeShort,
  awayShort,
  homeScore,
  awayScore,
  pickResult,
}: {
  homeShort: string;
  awayShort: string;
  homeScore: number | null;
  awayScore: number | null;
  pickResult: PickResult;
}) {
  if (pickResult == null || homeScore == null || awayScore == null) return null;
  if (homeScore === awayScore) return null;
  const winner = homeScore > awayScore ? homeShort : awayShort;
  const tone = pickResult === "hit" ? "text-signal" : "text-muted";
  return (
    <div className={`mt-2 text-center text-micro ${tone}`}>
      {winner} won, pick {pickResult === "hit" ? "hit" : "missed"}
    </div>
  );
}
