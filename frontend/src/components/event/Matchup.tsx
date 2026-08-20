"use client";

import Image from "next/image";
import { logoPath, matchupVisuals, type TeamVisual } from "@/lib/teams";
import { FollowButton } from "./FollowButton";

/**
 * The matchup as ONE line: both marks, both names, home indicated.
 *
 * Previously two stacked rows, each with a logo, an accent bar, a home badge
 * and a star — which gave identity the same footprint as the recommendation.
 * Identity is not the headline; it is how you know which game you are looking
 * at. One line, title-sized, with the accents reduced to a thin underline
 * beneath each mark so team colour still identifies without occupying a column.
 *
 * The "+" beside each name FOLLOWS that team. The star that favourites the
 * whole matchup lives at the card's corner, deliberately away from both names —
 * see FollowButton and FavoriteGameButton.
 *
 * Home is carried by weight rather than a badge: the home side is the one after
 * "@", which is the convention this audience already reads, and the badge was
 * competing with real controls. The relationship is stated for screen readers,
 * which cannot see weight.
 */
function Side({
  name,
  visual,
  accent,
  strong,
  isFollowed,
  onToggleFollow,
}: {
  name: string | null;
  visual: TeamVisual | null;
  accent: string;
  strong: boolean;
  isFollowed: (team: string | null | undefined) => boolean;
  onToggleFollow: (team: string) => void;
}) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="flex shrink-0 flex-col items-center">
        {visual ? (
          <Image src={logoPath(visual)} alt="" width={20} height={20} aria-hidden />
        ) : (
          <span aria-hidden className="h-5 w-5 rounded-full bg-raised" />
        )}
        <span
          aria-hidden
          className="mt-[2px] h-[2px] w-4"
          style={{ background: accent }}
        />
      </span>

      {/* `min-w-0` alongside truncate: without it the span's min-content width
          is the full team name, so it never actually truncates — it just makes
          its parent wider. */}
      <span
        className={`data min-w-0 truncate text-title ${
          strong ? "font-medium text-text" : "text-dim"
        }`}
      >
        {visual?.short ?? name}
      </span>

      {name ? (
        <FollowButton team={name} following={isFollowed(name)} onToggle={onToggleFollow} />
      ) : null}
    </span>
  );
}

export function Matchup({
  home,
  away,
  isFollowed,
  onToggleFollow,
}: {
  home: string | null;
  away: string | null;
  isFollowed: (team: string | null | undefined) => boolean;
  onToggleFollow: (team: string) => void;
}) {
  const { home: hv, away: av, homeAccent, awayAccent } = matchupVisuals(home, away);

  return (
    <div className="flex min-w-0 items-center gap-2">
      <Side
        name={away}
        visual={av}
        accent={awayAccent}
        strong={false}
        isFollowed={isFollowed}
        onToggleFollow={onToggleFollow}
      />
      <span aria-hidden className="shrink-0 text-meta text-faint">
        @
      </span>
      <Side
        name={home}
        visual={hv}
        accent={homeAccent}
        strong
        isFollowed={isFollowed}
        onToggleFollow={onToggleFollow}
      />
      <span className="sr-only">{home} is the home team</span>
    </div>
  );
}
