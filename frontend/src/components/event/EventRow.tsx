"use client";

import Link from "next/link";
import { BetControls } from "@/components/recommendation/BetControls";
import { AdvancedMetrics } from "@/components/advanced/AdvancedMetrics";
import { InfoPopover } from "@/components/primitives/InfoPopover";
import { TeamLogo } from "./Matchup";
import { FavoriteGameButton } from "./FavoriteGameButton";
import { KickoffTime } from "./KickoffTime";
import { MoveChip } from "./MoveChip";
import { STATUS_LABEL, kalshiUrl, shortUnscoreableReason } from "@/lib/copy";
import { confidence, opacityOf } from "@/lib/confidence";
import { cents, edgeCents, fairValueCents } from "@/lib/format";
import { matchupVisuals, teamVisual } from "@/lib/teams";
import type { NetMove } from "@/lib/moves";
import type { Divergence, Recommendation } from "@/lib/types";
import type { Mode } from "@/lib/mode";

/**
 * One event in the Rows density: the same facts as EventCard, one line tall.
 *
 * A row WITH a recommendation is a disclosure. The collapsed line carries the
 * pick, the order and the sportsbooks' price; opening it mounts the card's own
 * BetControls, so the stake arithmetic is the same component in both views.
 * A row WITHOUT one is a quiet line that links to the detail page, because
 * there is no bet to open.
 *
 * Two layouts, swapped at `md` (768px) rather than squeezed: the phone line
 * keeps logos, pick, order and time, and moves the star, the books price and
 * the edge into the opened panel. Between `md` and `lg` the books price moves
 * there too, so the headline keeps room to be read.
 *
 * The toggle is a real <button> laid over the line (the same overlay pattern as
 * the card's link), so it is keyboard operable with aria-expanded for free and
 * never has to contain the star. Everything clickable sits at z-20 above it.
 */

type RowProps = {
  d: Divergence;
  minBooks: number;
  mode: Mode;
  isFavoriteGame: boolean;
  onToggleFavoriteGame: (eventId: string) => void;
  move?: NetMove;
  onOpen: (d: Divergence) => void;
};

export function EventRow({
  open,
  onToggle,
  ...props
}: RowProps & { open: boolean; onToggle: (eventId: string) => void }) {
  const r = props.d.recommendation;
  if (!r) return <QuietRow {...props} />;
  return <RecommendationRow {...props} r={r} open={open} onToggle={onToggle} />;
}

function Logos({ d, size, cutout }: { d: Divergence; size: number; cutout: string }) {
  const { home, away, homeAccent, awayAccent } = matchupVisuals(d.home_team, d.away_team);
  return (
    <span aria-hidden className="flex shrink-0 items-center">
      <TeamLogo visual={away} name={d.away_team} accent={awayAccent} size={size} cutout={cutout} />
      <span className="-ml-2">
        <TeamLogo visual={home} name={d.home_team} accent={homeAccent} size={size} cutout={cutout} />
      </span>
    </span>
  );
}

function matchupText(d: Divergence): string {
  const away = teamVisual(d.away_team)?.short ?? d.away_team;
  const home = teamVisual(d.home_team)?.short ?? d.home_team;
  return `${away} @ ${home}`;
}

function Star({
  d,
  favorited,
  onToggle,
  size = "md",
}: {
  d: Divergence;
  favorited: boolean;
  onToggle: (eventId: string) => void;
  size?: "md" | "lg";
}) {
  return (
    <FavoriteGameButton
      size={size}
      label={`${d.away_team} at ${d.home_team}`}
      favorited={favorited}
      onToggle={() => onToggle(d.event_id)}
    />
  );
}

function Pill({ r, className = "" }: { r: Recommendation; className?: string }) {
  return (
    <span
      className={`row-pill tabular inline-block shrink-0 whitespace-nowrap rounded-full font-semibold text-signal ${className}`}
    >
      Buy {r.side === "yes" ? "Yes" : "No"} · {cents(r.price)}
    </span>
  );
}

function Books({ r, className = "" }: { r: Recommendation; className?: string }) {
  return (
    <span className={`tabular whitespace-nowrap text-[13px] text-[var(--row-muted)] ${className}`}>
      Books {fairValueCents(r.fair_value, r.price)}
    </span>
  );
}

function Edge({ r }: { r: Recommendation }) {
  return (
    <span
      title="Sportsbooks' price minus the Kalshi price"
      className="tabular shrink-0 whitespace-nowrap rounded-lg bg-raised px-2 py-1 text-micro font-semibold text-signal"
    >
      {edgeCents(r.fair_value, r.price)}
    </span>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      width="16"
      height="16"
      className={`shrink-0 transition-transform duration-200 motion-reduce:transition-none ${
        open ? "rotate-180 text-signal" : "text-faint"
      }`}
    >
      <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function RecommendationRow({
  d,
  r,
  minBooks,
  mode,
  isFavoriteGame,
  onToggleFavoriteGame,
  move,
  onOpen,
  open,
  onToggle,
}: RowProps & { r: Recommendation; open: boolean; onToggle: (eventId: string) => void }) {
  const yes = r.side === "yes";
  const short = teamVisual(r.team)?.short ?? r.team;
  const headline = `${short} to ${yes ? "win" : "lose"}`;
  const kalshi = kalshiUrl(d.kalshi_series, d.kalshi_event_ticker);
  const books = d.n_books ?? 0;
  const conf = confidence(d, minBooks);
  const panelId = `row-panel-${d.event_id}`;

  return (
    <article
      data-event-id={d.event_id}
      style={{ opacity: opacityOf(d) }}
      className={`event-row relative min-w-0 overflow-hidden rounded-xl border transition-[opacity,border-color] ${
        open ? "border-[var(--row-open-border)]" : "border-[var(--row-border)] hover:border-border-lit"
      } ${isFavoriteGame ? "card-pinned" : ""}`}
    >
      <div className="relative">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          aria-label={`${headline}, buy ${yes ? "Yes" : "No"} at ${cents(r.price)}. ${d.away_team} at ${d.home_team}.`}
          onClick={() => onToggle(d.event_id)}
          className="absolute inset-0 z-10 w-full cursor-pointer rounded-xl"
        />

        {/* --- desktop line (≥768px) --------------------------------------- */}
        <div className="hidden h-16 items-center gap-3 px-4 md:flex lg:gap-3.5">
          <span className="relative z-20 -ml-1.5">
            <Star d={d} favorited={isFavoriteGame} onToggle={onToggleFavoriteGame} />
          </span>
          <Logos d={d} size={34} cutout="var(--row-surface)" />
          <span className="w-[150px] min-w-0 shrink-0 lg:w-[200px]">
            <span className="block truncate text-[14px] font-medium text-text">{matchupText(d)}</span>
            <span className="block truncate text-micro text-faint">
              <KickoffTime iso={d.scheduled_start} separator=", " />
            </span>
          </span>
          <span className="display-medium min-w-0 flex-1 truncate text-[17px] text-text">
            {headline}
          </span>
          <Pill r={r} className="px-3.5 py-1.5 text-[13px]" />
          <Books r={r} className="hidden w-[90px] text-right lg:block" />
          <Edge r={r} />
          <Chevron open={open} />
        </div>

        {/* --- phone line (<768px) ----------------------------------------- */}
        <div className="flex min-h-[68px] items-center gap-2.5 px-3 py-2.5 md:hidden">
          <Logos d={d} size={28} cutout="var(--row-surface)" />
          <span className="min-w-0 flex-1">
            <span className="display-medium block text-[14px] leading-tight text-text">
              {headline}
            </span>
            <span className="mt-1 block truncate text-micro text-faint">{matchupText(d)}</span>
          </span>
          <span className="flex shrink-0 flex-col items-end">
            <Pill r={r} className="px-2.5 py-1 text-micro" />
            <span className="mt-1 whitespace-nowrap text-micro text-faint">
              <KickoffTime iso={d.scheduled_start} separator=", " />
            </span>
          </span>
        </div>
      </div>

      {open ? (
        <div
          id={panelId}
          className="border-t border-[var(--row-border)] bg-surface px-3 py-4 md:px-6 md:py-5"
        >
          {/* What the collapsed line had no room for at this width. */}
          <div className="mb-4 flex items-center gap-3 lg:hidden">
            <span className="relative z-20 md:hidden">
              <Star d={d} favorited={isFavoriteGame} onToggle={onToggleFavoriteGame} size="lg" />
            </span>
            <Books r={r} />
            <span className="md:hidden">
              <Edge r={r} />
            </span>
          </div>

          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] md:gap-8">
            <div className="min-w-0">
              <BetControls rec={r} teamShort={short} />
            </div>

            <div className="flex min-w-0 flex-col gap-3">
              <p className="text-[13px] leading-relaxed text-muted">
                Pays $1 if {short} {yes ? "win" : "lose"}. Sportsbooks say{" "}
                <span className="tabular text-dim">{fairValueCents(r.fair_value, r.price)}</span>{" "}
                across {books} {books === 1 ? "sportsbook" : "sportsbooks"}.
              </p>
              <span className="relative z-20 inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
                <span>
                  Strength: <span className="font-medium text-text">{conf.label}</span>
                </span>
                <InfoPopover term="confidence" />
                {move ? <MoveChip move={move} /> : null}
              </span>
              {mode === "advanced" ? <AdvancedMetrics d={d} /> : null}

              <RowLinks d={d} kalshi={kalshi} onOpen={onOpen} className="mt-auto" />
            </div>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function RowLinks({
  d,
  kalshi,
  onOpen,
  className = "",
}: {
  d: Divergence;
  kalshi: string | null;
  onOpen: (d: Divergence) => void;
  className?: string;
}) {
  return (
    <div
      className={`relative z-20 flex flex-wrap items-center gap-x-5 gap-y-1.5 pt-1 text-[13px] font-medium ${className}`}
    >
      {kalshi ? (
        <a
          href={kalshi}
          target="_blank"
          rel="noopener noreferrer"
          title="Opens this game on Kalshi"
          onClick={(e) => e.stopPropagation()}
          className="tap text-signal underline-offset-4 hover:underline"
        >
          Open on Kalshi ↗
        </a>
      ) : null}
      {d.is_arbitrage && d.arbitrage?.includes_kalshi ? (
        <span className="flex items-center gap-1 font-normal">
          <span className="text-arb">Cross-platform arbitrage</span>
          <InfoPopover term="arbitrage" />
        </span>
      ) : null}
      <Link
        href={`/events/${d.event_id}`}
        onClick={(e) => {
          e.stopPropagation();
          onOpen(d);
        }}
        className="tap ml-auto text-[var(--row-muted)] underline-offset-4 hover:text-dim hover:underline"
      >
        Details →
      </Link>
    </div>
  );
}

/**
 * No recommendation: nothing to open, so the whole line links to the detail
 * page instead. Unscoreable games get a dashed edge — the same "we could not
 * compare these" mark as the fold below each group — while a scored game with
 * no edge keeps a solid one, because that is a real reading, not a gap.
 */
function QuietRow({
  d,
  minBooks,
  isFavoriteGame,
  onToggleFavoriteGame,
  onOpen,
}: RowProps) {
  const scored = d.status === "scored";
  const reason = shortUnscoreableReason(d, minBooks);
  const arb = d.is_arbitrage && d.arbitrage?.includes_kalshi;
  const long =
    d.status === "scored" ? "No edge right now" : `Can’t score yet. ${QUIET_TAIL[d.status]}`;
  const brief = scored ? "No edge right now" : "Can’t score yet";

  return (
    <article
      data-event-id={d.event_id}
      style={{ opacity: opacityOf(d) }}
      title={reason ?? undefined}
      className={`relative min-w-0 rounded-xl border transition-[opacity,border-color] hover:border-border-lit ${
        scored ? "border-[var(--row-border)]" : "border-dashed border-[var(--row-border)]"
      } ${isFavoriteGame ? "card-pinned" : ""}`}
    >
      <Link
        href={`/events/${d.event_id}`}
        onClick={() => onOpen(d)}
        aria-label={`${d.away_team} at ${d.home_team}: ${long}. Full detail`}
        className="absolute inset-0 z-10 rounded-xl"
      />

      <div className="hidden h-[52px] items-center gap-3 px-4 md:flex lg:gap-3.5">
        <span className="relative z-20 -ml-1.5">
          <Star d={d} favorited={isFavoriteGame} onToggle={onToggleFavoriteGame} />
        </span>
        <Logos d={d} size={28} cutout="var(--bg)" />
        <span className="w-[150px] min-w-0 shrink-0 truncate text-[14px] text-[var(--row-muted)] lg:w-[200px]">
          {matchupText(d)}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px] text-faint">
          {long}
          {arb ? <span className="ml-2 text-arb">Cross-platform arbitrage</span> : null}
        </span>
        {!scored ? (
          <span className="shrink-0 text-micro text-faint">{STATUS_LABEL[d.status]}</span>
        ) : null}
        <span className="shrink-0 whitespace-nowrap text-micro text-faint">
          <KickoffTime iso={d.scheduled_start} separator=", " />
        </span>
      </div>

      <div className="flex min-h-[52px] items-center gap-2.5 px-3 py-2 md:hidden">
        <Logos d={d} size={24} cutout="var(--bg)" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] text-[var(--row-muted)]">{matchupText(d)}</span>
          <span className="block truncate text-micro text-faint">
            {brief}
          </span>
        </span>
        <span className="shrink-0 whitespace-nowrap text-micro text-faint">
          <KickoffTime iso={d.scheduled_start} separator=", " />
        </span>
      </div>
    </article>
  );
}

/** The second sentence of the desktop quiet row, by reason. */
const QUIET_TAIL: Record<Exclude<Divergence["status"], "scored">, string> = {
  single_source_no_divergence: "Waiting on a second price.",
  insufficient_consensus: "Waiting on more sportsbooks.",
  incomparable_outcomes: "The two sources disagree on the teams.",
};
