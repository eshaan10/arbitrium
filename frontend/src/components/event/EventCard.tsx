"use client";

import Link from "next/link";
import { Badge } from "@/components/primitives";
import { InfoPopover } from "@/components/primitives/InfoPopover";
import { AnimatedNumber } from "@/components/primitives/AnimatedNumber";
import { Evidence } from "@/components/recommendation/Evidence";
import { StakeSimulator } from "@/components/recommendation/StakeSimulator";
import { AdvancedMetrics } from "@/components/advanced/AdvancedMetrics";
import { Matchup } from "./Matchup";
import { FavoriteGameButton } from "./FavoriteGameButton";
import { MoveChip } from "./MoveChip";
import { STATUS_LABEL, kalshiUrl, shortUnscoreableReason } from "@/lib/copy";
import { opacityOf } from "@/lib/confidence";
import { cents, timeToKickoff } from "@/lib/format";
import { KickoffTime } from "./KickoffTime";
import type { NetMove } from "@/lib/moves";
import type { Divergence } from "@/lib/types";
import type { Mode } from "@/lib/mode";

/**
 * Three zones, in descending weight:
 *
 *   IDENTITY  — which game, when. Meta-sized, quiet.
 *   HERO      — the price, at display size. The one thing a glance should land
 *               on. Nothing else on the card comes close to its weight.
 *   EVIDENCE  — the numbers behind it, one line, with the sentence disclosed.
 *   ACTIONS   — stake, links, tags. Below a hairline, meta-sized.
 *
 * A card with no recommendation gets a genuinely quiet hero rather than a loud
 * empty one: the honest answer there is "nothing to do", and shouting it would
 * make 256 unscoreable events compete with 23 real ones.
 */
export function EventCard({
  d,
  minBooks,
  mode,
  isFollowed,
  onToggleFollow,
  isFavoriteGame,
  onToggleFavoriteGame,
  move,
  onOpen,
}: {
  d: Divergence;
  minBooks: number;
  mode: Mode;
  isFollowed: (team: string | null | undefined) => boolean;
  onToggleFollow: (team: string) => void;
  isFavoriteGame: boolean;
  onToggleFavoriteGame: (eventId: string) => void;
  move?: NetMove;
  onOpen: (d: Divergence) => void;
}) {
  const r = d.recommendation;
  const kalshi = kalshiUrl(d.kalshi_series);
  const reason = shortUnscoreableReason(d, minBooks);

  return (
    <article
      data-event-id={d.event_id}
      style={{ opacity: opacityOf(d) }}
      className={`relative flex flex-col rounded-lg border bg-surface p-4 transition-[opacity,border-color] hover:border-border-lit focus-within:border-border-lit ${
        r ? "card-actionable border-[var(--border-lit)]" : "border-border"
      } ${isFavoriteGame ? "card-pinned" : ""}`}
    >
      {/* Card-wide click target. A real positioned element, not a stretched
          ::after on an sr-only link — sr-only sets overflow:hidden and clips the
          pseudo-element, which silently leaves the card unclickable. Controls
          sit at z-20 above it. */}
      <Link
        href={`/events/${d.event_id}`}
        onClick={() => onOpen(d)}
        aria-label={`${d.away_team} at ${d.home_team} — full detail`}
        className="absolute inset-0 z-10 rounded-lg"
      />

      {/* --- identity ------------------------------------------------------ */}
      <div className="flex items-start justify-between gap-3">
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

      <div className="mt-1 flex items-center gap-2 text-micro text-faint">
        {/* Genuinely clock-dependent: the server computes "in 3d" at request
            time and the browser at hydration. Coarse enough that they agree in
            practice, and harmless when they don't — unlike the absolute time
            beside it, which is a fixed fact and is formatted deterministically. */}
        <span className="text-muted" suppressHydrationWarning>
          {timeToKickoff(d.scheduled_start)}
        </span>
        <KickoffTime iso={d.scheduled_start} />
        {move ? <MoveChip move={move} /> : null}
      </div>

      {/* --- hero ---------------------------------------------------------- */}
      {r ? (
        <div className="mt-4">
          <div className="text-micro uppercase tracking-[0.08em] text-signal-600">
            Buy {r.side} · {r.team}
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <AnimatedNumber
              value={r.price}
              format={cents}
              className="tabular text-display font-semibold text-text"
            />
            <span className="text-meta text-muted">per contract</span>
          </div>
        </div>
      ) : (
        <div className="mt-4">
          <div className="text-title text-muted">
            {d.status === "scored" ? "No edge right now" : "Can’t be scored yet"}
          </div>
        </div>
      )}

      {/* --- evidence ------------------------------------------------------ */}
      <div className="mt-3">
        {reason ? (
          <p className="max-w-[58ch] text-meta leading-relaxed text-muted">{reason}</p>
        ) : (
          <Evidence d={d} minBooks={minBooks} />
        )}
      </div>

      {mode === "advanced" ? (
        <div className="mt-3">
          <AdvancedMetrics d={d} />
        </div>
      ) : null}

      {/* --- actions ------------------------------------------------------- */}
      <div className="mt-auto pt-3">
        {r ? (
          <div className="border-t border-border pt-2.5">
            <StakeSimulator rec={r} />
          </div>
        ) : null}

        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border pt-2.5 text-meta">
          {kalshi ? (
            <a
              href={kalshi}
              target="_blank"
              rel="noopener noreferrer"
              title="Opens the Kalshi series page for this league"
              onClick={(e) => e.stopPropagation()}
              className="relative z-20 text-signal-600 hover:text-signal"
            >
              ↗ Kalshi
            </a>
          ) : null}

          {d.is_arbitrage && d.arbitrage?.includes_kalshi ? (
            <span className="flex items-center gap-1">
              <span className="text-arb">Cross-platform arbitrage</span>
              <InfoPopover term="arbitrage" />
            </span>
          ) : null}

          <span className="ml-auto text-faint transition-colors group-hover:text-muted">
            Details →
          </span>
        </div>
      </div>
    </article>
  );
}
