"use client";

import Link from "next/link";
import { Badge } from "@/components/primitives";
import { Chevron, Logos, matchupText, PregameTag } from "./EventRow";
import { Scoreboard } from "./Scoreboard";
import { cents, fairValueCents } from "@/lib/format";
import { finalLive, finalScoreLine, pickHeadline, weSaid, winnerLine } from "@/lib/finals";
import type { FinalGame, PickResult } from "@/lib/types";

/**
 * A finished game in "In progress or past".
 *
 * It shows what we said before the game and how that turned out, never what
 * Kalshi says now: a settled market sits at 0 or 100 cents, and printing that
 * beside the pick would read as a price. The snapshot is the one recorded when
 * the call was flagged, the same calibration row that pick_result grades.
 *
 * A game with no flagged call still opens to its final score; it just has no
 * badge, no snapshot and no "We said" line.
 */
export function FinalRow({
  f,
  open,
  onToggle,
  onOpen,
}: {
  f: FinalGame;
  open: boolean;
  onToggle: (eventId: string) => void;
  onOpen?: (f: FinalGame) => void;
}) {
  const headline = pickHeadline(f);
  const panelId = `final-panel-${f.event_id}`;
  const said = weSaid(f);

  return (
    <article
      data-event-id={f.event_id}
      className={`event-row relative min-w-0 overflow-hidden rounded-xl border transition-[border-color] ${
        open ? "border-[var(--row-open-border)]" : "border-[var(--row-border)] hover:border-border-lit"
      }`}
    >
      <div className="relative">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          aria-label={`${f.away_team} at ${f.home_team}, final ${f.away_score} to ${f.home_score}.${
            headline ? ` We said ${headline}.` : ""
          }`}
          onClick={() => onToggle(f.event_id)}
          className="absolute inset-0 z-10 w-full cursor-pointer rounded-xl"
        />

        {/* --- desktop line (≥768px) --------------------------------------- */}
        <div className="hidden h-16 items-center gap-3 px-4 md:flex lg:gap-3.5">
          <Logos d={f} size={34} cutout="var(--row-surface)" />
          <span className="w-[150px] min-w-0 shrink-0 lg:w-[200px]">
            <span className="block truncate text-[14px] font-medium text-text">{matchupText(f)}</span>
            <span className="tabular block truncate text-micro text-faint">{finalScoreLine(f)}</span>
          </span>
          <span
            className={`display-medium min-w-0 flex-1 truncate text-[17px] ${
              headline ? "text-text" : "text-muted"
            }`}
          >
            {headline ?? winnerLine(f)}
          </span>
          <PickBadge result={f.pick_result} />
          {f.flagged ? (
            <>
              <PregameTag />
              <span className="tabular shrink-0 whitespace-nowrap text-[13px] text-faint">
                {f.flagged.side === "yes" ? "Yes" : "No"} at {cents(f.flagged.price)}
              </span>
              <span className="tabular hidden w-[90px] shrink-0 whitespace-nowrap text-right text-[13px] text-faint lg:block">
                Books {fairValueCents(f.flagged.fair_value, f.flagged.price)}
              </span>
            </>
          ) : null}
          <Chevron open={open} />
        </div>

        {/* --- phone line (<768px) ----------------------------------------- */}
        <div className="flex min-h-[68px] items-center gap-2.5 px-3 py-2.5 md:hidden">
          <Logos d={f} size={28} cutout="var(--row-surface)" />
          <span className="min-w-0 flex-1">
            <span
              className={`display-medium block text-[14px] leading-tight ${
                headline ? "text-text" : "text-muted"
              }`}
            >
              {headline ?? winnerLine(f)}
            </span>
            <span className="mt-1 block truncate text-micro text-faint">{matchupText(f)}</span>
          </span>
          <span className="flex shrink-0 flex-col items-end gap-1">
            <PickBadge result={f.pick_result} />
            <span className="tabular whitespace-nowrap text-micro text-faint">
              {finalScoreLine(f)}
            </span>
          </span>
        </div>
      </div>

      {open ? (
        <div
          id={panelId}
          className="border-t border-[var(--row-border)] bg-surface px-3 py-4 md:px-6 md:py-5"
        >
          {f.flagged ? (
            // What the collapsed phone line had no room for.
            <div className="mb-4 flex flex-wrap items-center gap-3 text-[13px] text-faint md:hidden">
              <PregameTag />
              <span className="tabular">
                {f.flagged.side === "yes" ? "Yes" : "No"} at {cents(f.flagged.price)}
              </span>
              <span className="tabular">Books {fairValueCents(f.flagged.fair_value, f.flagged.price)}</span>
            </div>
          ) : null}
          <div className="max-w-[560px]">
            <Scoreboard
              home_team={f.home_team}
              away_team={f.away_team}
              scheduled_start={f.scheduled_start}
              sport={f.sport}
              live={finalLive(f)}
            />
          </div>
          {said ? <p className="mt-4 text-[13px] leading-relaxed text-muted">{said}</p> : null}
          <div className="relative z-20 mt-3 flex text-[13px] font-medium">
            <Link
              href={`/events/${f.event_id}`}
              onClick={(e) => {
                e.stopPropagation();
                onOpen?.(f);
              }}
              className="tap ml-auto text-[var(--row-muted)] underline-offset-4 hover:text-dim hover:underline"
            >
              Details →
            </Link>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function PickBadge({ result }: { result: PickResult }) {
  if (result == null) return null;
  return (
    <span className="shrink-0">
      <Badge tone={result === "hit" ? "signal" : "muted"}>
        {result === "hit" ? "Pick hit" : "Pick missed"}
      </Badge>
    </span>
  );
}
