"use client";

/**
 * FOLLOW a team — "+" beside the team name.
 *
 * Distinct from favouriting a game in every channel that matters: a different
 * verb ("Follow" vs "Favorite"), a different glyph (+/✓ vs a star), a different
 * shape (an enclosed chip vs a bare mark), and a different position (inline
 * with the team it applies to, rather than at the card's corner). Following is
 * an ongoing subscription to a team; favouriting is a pin on one matchup, and
 * the two must never look like variants of one control.
 */
export function FollowButton({
  team,
  following,
  onToggle,
}: {
  team: string;
  following: boolean;
  onToggle: (team: string) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={following}
      aria-label={following ? `Unfollow ${team}` : `Follow ${team}`}
      title={
        following
          ? `Following ${team} — every game they play appears in My Teams`
          : `Follow ${team} to see every game they play`
      }
      onClick={(e) => {
        // The whole card navigates; this control must not.
        e.preventDefault();
        e.stopPropagation();
        onToggle(team);
      }}
      className={`relative z-20 flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-[4px] border text-[10px] leading-none transition-colors ${
        following
          ? "border-signal bg-signal text-white"
          : "border-border-lit text-faint hover:border-signal hover:text-signal"
      }`}
    >
      <span aria-hidden>{following ? "✓" : "+"}</span>
    </button>
  );
}
