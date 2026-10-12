"use client";

import Link from "next/link";
import { Badge } from "@/components/primitives";
import { InfoPopover } from "@/components/primitives/InfoPopover";
import { Evidence } from "@/components/recommendation/Evidence";
import { BetControls } from "@/components/recommendation/BetControls";
import { Matchup } from "./Matchup";
import { FavoriteGameButton } from "./FavoriteGameButton";
import { MoveChip } from "./MoveChip";
import { STATUS_LABEL, kalshiUrl, shortUnscoreableReason } from "@/lib/copy";
import { confidence, opacityOf } from "@/lib/confidence";
import { cents, fairValueCents, timeToKickoffLong } from "@/lib/format";
import { teamVisual } from "@/lib/teams";
import { KickoffTime } from "./KickoffTime";
import { SignalMeter } from "./Signal";
import type { NetMove } from "@/lib/moves";
import type { Divergence, Recommendation } from "@/lib/types";
import { gameState, hasScoreboard, isLive } from "@/lib/liveState";
import { Scoreboard } from "./Scoreboard";

/**
 * One event in the list.
 *
 * A card WITH a directional recommendation is a RecommendationCard (below):
 * the pick as a headline, the exact Kalshi order, and a working bet.
 *
 * A card without one gets a genuinely quiet treatment — small header, one
 * muted line, the reason or the evidence. The honest answer there is "nothing
 * to do", and shouting it would make ~190 unscoreable or dead-even events
 * compete with the dozen real ones. Arbitrage-only events stay on this path
 * and keep their tag in the footer.
 */
export function EventCard({
  d,
  minBooks,
  isFollowed,
  onToggleFollow,
  isFavoriteGame,
  onToggleFavoriteGame,
  move,
  onOpen,
  signalScale,
}: {
  d: Divergence;
  minBooks: number;
  isFollowed: (team: string | null | undefined) => boolean;
  onToggleFollow: (team: string) => void;
  isFavoriteGame: boolean;
  onToggleFavoriteGame: (eventId: string) => void;
  move?: NetMove;
  onOpen: (d: Divergence) => void;
  /** Strongest signal in the list this card sits in; omit to hide the meter. */
  signalScale?: number;
}) {
  const r = d.recommendation;
  const kalshi = kalshiUrl(d.kalshi_series, d.kalshi_event_ticker);
  const reason = shortUnscoreableReason(d, minBooks);

  if (r) {
    return (
      <RecommendationCard
        d={d}
        r={r}
        minBooks={minBooks}
        isFollowed={isFollowed}
        onToggleFollow={onToggleFollow}
        isFavoriteGame={isFavoriteGame}
        onToggleFavoriteGame={onToggleFavoriteGame}
        move={move}
        onOpen={onOpen}
        kalshi={kalshi}
        signalScale={signalScale}
      />
    );
  }

  return (
    <article
      data-event-id={d.event_id}
      style={{ opacity: opacityOf(d) }}
      // `min-w-0` is load-bearing, not tidiness: a grid item defaults to
      // min-width:auto, so the card's min-CONTENT width sets the track width.
      // A long team name therefore pushed the whole single-column grid past
      // the viewport and the entire page scrolled sideways on a phone — the
      // card looked innocent because it was merely filling the track it had
      // been given.
      className={`card relative flex min-w-0 flex-col transition-[opacity,border-color] hover:border-border-lit focus-within:border-border-lit ${
        isFavoriteGame ? "card-pinned" : ""
      }`}
    >
      <CardLink d={d} onOpen={onOpen} />

      {/* --- identity ------------------------------------------------------ */}
      <div className="flex items-start justify-between gap-2 sm:gap-3">
        <Matchup
          home={d.home_team}
          away={d.away_team}
          isFollowed={isFollowed}
          onToggleFollow={onToggleFollow}
        />
        <div className="flex shrink-0 items-center gap-2">
          {d.status !== "scored" ? (
            <Badge tone={d.status === "incomparable_outcomes" ? "warn" : "muted"}>
              {STATUS_LABEL[d.status]}
            </Badge>
          ) : null}
          {/* Applies to the MATCHUP, so it sits at the card's corner rather
              than beside either team. */}
          <FavoriteGameButton
            label={`${d.away_team} at ${d.home_team}`}
            favorited={isFavoriteGame}
            onToggle={() => onToggleFavoriteGame(d.event_id)}
          />
        </div>
      </div>

      <DateLine d={d} move={move} />

      {/* --- quiet hero ---------------------------------------------------- */}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px] text-muted">
        {d.status === "scored" ? "No edge right now" : "Can’t be scored yet"}
        {d.status === "scored" && signalScale != null ? (
          <SignalLine d={d} scale={signalScale} />
        ) : null}
      </div>

      {/* --- evidence ------------------------------------------------------ */}
      <div className="mt-3">
        {reason ? (
          <p className="prose max-w-[58ch] text-[13px] leading-relaxed text-muted">{reason}</p>
        ) : (
          <Evidence d={d} minBooks={minBooks} />
        )}
      </div>

      {hasScoreboard(d) ? (
        <div className="mt-3">
          <Scoreboard
            home_team={d.home_team}
            away_team={d.away_team}
            scheduled_start={d.scheduled_start}
            sport={d.sport}
            live={d.live}
            pick_result={d.pick_result}
          />
        </div>
      ) : null}

      <div className="mt-auto pt-3">
        <Footer d={d} kalshi={kalshi} />
      </div>
    </article>
  );
}

/**
 * Card-wide click target. A real positioned element, not a stretched ::after
 * on an sr-only link — sr-only sets overflow:hidden and clips the
 * pseudo-element, which silently leaves the card unclickable. Every control
 * sits at z-20 above it.
 */
function CardLink({ d, onOpen }: { d: Divergence; onOpen: (d: Divergence) => void }) {
  return (
    <Link
      href={`/events/${d.event_id}`}
      onClick={() => onOpen(d)}
      aria-label={`${d.away_team} at ${d.home_team} — full detail`}
      className="absolute inset-0 z-10 rounded-[var(--r-card)]"
    />
  );
}

function DateLine({ d, move }: { d: Divergence; move?: NetMove }) {
  const state = gameState(d);
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-faint">
      {state === "live" ? (
        <span className="inline-flex items-center gap-1 text-[var(--live)]">
          <span
            aria-hidden
            className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--live)] motion-safe:animate-pulse"
          />
          LIVE
        </span>
      ) : state === "final" ? (
        <span>Final</span>
      ) : state === "started" ? (
        <span>Started</span>
      ) : (
        <span>
          <KickoffTime iso={d.scheduled_start} separator=", " />
          <span aria-hidden> · </span>
          <span suppressHydrationWarning>{timeToKickoffLong(d.scheduled_start)}</span>
        </span>
      )}
      {move ? <MoveChip move={move} /> : null}
    </div>
  );
}

function Footer({ d, kalshi }: { d: Divergence; kalshi: string | null }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border pt-3 text-[13px]">
      {kalshi ? (
        <a
          href={kalshi}
          target="_blank"
          rel="noopener noreferrer"
          title="Opens this game on Kalshi"
          onClick={(e) => e.stopPropagation()}
          className="tap relative z-20 font-medium text-signal underline-offset-4 hover:underline"
        >
          Open on Kalshi ↗
        </a>
      ) : null}

      {d.is_arbitrage && d.arbitrage?.includes_kalshi ? (
        <span className="relative z-20 flex items-center gap-1">
          <span className="text-arb">Cross-platform arbitrage</span>
          <InfoPopover term="arbitrage" />
        </span>
      ) : null}

      <span className="ml-auto text-faint">Details →</span>
    </div>
  );
}

/**
 * How much to trust this recommendation: the same four-step rating the rest
 * of the app calls confidence (lib/confidence.ts — how many sportsbooks agree,
 * and how many contracts are actually resting at the price). Bars for a
 * glance, the word for everyone, since a bar count alone is colour and shape.
 */
function Strength({ bars, label }: { bars: number; label: string }) {
  return (
    <span className="relative z-20 inline-flex items-center gap-1.5 text-[13px] text-muted">
      <span aria-hidden className="flex items-end gap-[2px]">
        {[1, 2, 3, 4].map((i) => (
          <i
            key={i}
            style={{ height: `${4 + i * 2}px` }}
            className={`w-[3px] rounded-[1px] ${i <= bars ? "bg-signal" : "bg-[var(--border-lit)]"}`}
          />
        ))}
      </span>
      <span>
        Strength: <span className="font-medium text-text">{label}</span>
      </span>
      <InfoPopover term="confidence" />
    </span>
  );
}

/** The meter, its word, and its "?", above the card's whole-card link. */
function SignalLine({ d, scale }: { d: Divergence; scale: number }) {
  return (
    <span className="relative z-20 inline-flex items-center gap-1.5">
      <SignalMeter d={d} scale={scale} label />
      <InfoPopover term="signal" />
    </span>
  );
}

/**
 * A card with a directional recommendation. Top to bottom:
 *
 *   HEADER    both teams, the date line, the favourite star
 *   HEADLINE  the pick in plain words — the largest thing on the card
 *   ACTION    the exact Kalshi order, its strength, and one sentence of why
 *   BET       an amount, a slider, and both outcomes
 *   FOOTER    Open on Kalshi, arbitrage tag
 *
 * The headline is plain language ("Seahawks to lose"); the pill beside it is
 * the literal order ("Buy No · 39¢"). Neither replaces the other: the first is
 * what a reader understands, the second is what they would actually click.
 */
function RecommendationCard({
  d,
  r,
  minBooks,
  isFollowed,
  onToggleFollow,
  isFavoriteGame,
  onToggleFavoriteGame,
  move,
  onOpen,
  kalshi,
  signalScale,
}: {
  d: Divergence;
  r: Recommendation;
  minBooks: number;
  isFollowed: (team: string | null | undefined) => boolean;
  onToggleFollow: (team: string) => void;
  isFavoriteGame: boolean;
  onToggleFavoriteGame: (eventId: string) => void;
  move?: NetMove;
  onOpen: (d: Divergence) => void;
  kalshi: string | null;
  signalScale?: number;
}) {
  const yes = r.side === "yes";
  const short = teamVisual(r.team)?.short ?? r.team;
  const conf = confidence(d, minBooks);
  const books = d.n_books ?? 0;
  const live = isLive(d);

  return (
    <article
      data-event-id={d.event_id}
      style={{ opacity: opacityOf(d) }}
      className={`card card-actionable relative flex min-w-0 flex-col transition-[opacity,border-color] hover:border-border-lit focus-within:border-border-lit ${
        isFavoriteGame ? "card-pinned" : ""
      }`}
    >
      <CardLink d={d} onOpen={onOpen} />

      {/* --- header -------------------------------------------------------- */}
      <div className="flex items-start justify-between gap-3">
        <Matchup
          size="lg"
          home={d.home_team}
          away={d.away_team}
          isFollowed={isFollowed}
          onToggleFollow={onToggleFollow}
        />
        <FavoriteGameButton
          size="lg"
          label={`${d.away_team} at ${d.home_team}`}
          favorited={isFavoriteGame}
          onToggle={() => onToggleFavoriteGame(d.event_id)}
        />
      </div>
      <DateLine d={d} move={move} />

      {/* --- headline ------------------------------------------------------ */}
      <h3 className="display card-headline mt-4 text-text">
        {short} to {yes ? "win" : "lose"}
      </h3>

      {/* --- the order, its strength, and why ----------------------------- */}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="tabular shrink-0 rounded-md bg-signal px-2 py-0.5 text-[13px] font-semibold text-bg">
          Buy {yes ? "Yes" : "No"} · {cents(r.price)}
        </span>
        <Strength bars={conf.bars} label={conf.label} />
        {signalScale != null ? <SignalLine d={d} scale={signalScale} /> : null}
      </div>
      <p className={`mt-2 text-[13px] leading-relaxed ${live ? "text-faint" : "text-muted"}`}>
        Pays $1 if they {yes ? "win" : "lose"}. {live ? "Pregame s" : "S"}portsbooks say{" "}
        <span className="tabular text-dim">{fairValueCents(r.fair_value, r.price)}</span> across{" "}
        {books} {books === 1 ? "sportsbook" : "sportsbooks"}.
      </p>

      {live ? (
        <p className="mt-2 text-micro text-muted">
          Game in progress. Price reflects the current score.
        </p>
      ) : null}

      {hasScoreboard(d) ? (
        <div className="mt-3">
          <Scoreboard
            home_team={d.home_team}
            away_team={d.away_team}
            scheduled_start={d.scheduled_start}
            sport={d.sport}
            live={d.live}
            pick_result={d.pick_result}
          />
        </div>
      ) : null}

      {/* --- bet ----------------------------------------------------------- */}
      <div className="mt-4">
        <BetControls rec={r} teamShort={short} />
      </div>

      <div className="mt-auto pt-4">
        <Footer d={d} kalshi={kalshi} />
      </div>
    </article>
  );
}
