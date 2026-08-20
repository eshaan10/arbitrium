"use client";

/**
 * FAVORITE a game — a star at the card's corner.
 *
 * Applies to the matchup, not to either team, so it deliberately sits away from
 * both team names. A favourited card also gains a pinned edge (see EventCard),
 * which makes the state legible in a scan without reading the star.
 */
export function FavoriteGameButton({
  label,
  favorited,
  onToggle,
}: {
  /** Human description of the matchup, for the accessible name. */
  label: string;
  favorited: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={favorited}
      aria-label={favorited ? `Unpin ${label}` : `Pin ${label}`}
      title={favorited ? "Pinned to My Games" : "Pin this matchup to My Games"}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
      className={`tap relative z-20 -m-1 shrink-0 rounded-sm p-1 text-[15px] leading-none transition-colors ${
        favorited ? "text-signal" : "text-faint hover:text-dim"
      }`}
    >
      <span aria-hidden>{favorited ? "★" : "☆"}</span>
    </button>
  );
}
