"use client";

/**
 * FAVORITE a game — a star at the card's corner.
 *
 * Applies to the matchup, not to either team, so it deliberately sits away from
 * both team names. A favourited card also gains a pinned edge (see EventCard),
 * which makes the state legible in a scan without reading the star.
 *
 * `lg` is the recommendation card's 36×36 bordered button; `sm` is the bare
 * glyph used in denser places; `md` is that glyph in a 36×36 button, for the
 * dashboard rows. All expand to a 44px hit area on touch (.tap).
 */
export function FavoriteGameButton({
  label,
  favorited,
  onToggle,
  size = "sm",
}: {
  /** Human description of the matchup, for the accessible name. */
  label: string;
  favorited: boolean;
  onToggle: () => void;
  size?: "sm" | "md" | "lg";
}) {
  const common = {
    type: "button" as const,
    "aria-pressed": favorited,
    "aria-label": favorited ? `Unpin ${label}` : `Pin ${label}`,
    title: favorited ? "Pinned to My Games" : "Pin this matchup to My Games",
    onClick: (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      onToggle();
    },
  };

  if (size === "lg") {
    return (
      <button
        {...common}
        className={`tap relative z-20 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition-colors ${
          favorited
            ? "border-signal bg-signal-950 text-signal"
            : "border-border-lit text-signal hover:border-signal"
        }`}
      >
        <svg aria-hidden viewBox="0 0 24 24" width="17" height="17">
          <path
            d="M12 2.8l2.82 5.72 6.31.92-4.57 4.45 1.08 6.29L12 17.21l-5.64 2.97 1.08-6.29-4.57-4.45 6.31-.92z"
            fill={favorited ? "currentColor" : "none"}
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    );
  }

  if (size === "md") {
    return (
      <button
        {...common}
        className={`tap relative z-20 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[18px] leading-none transition-colors ${
          favorited ? "text-signal" : "text-faint hover:text-dim"
        }`}
      >
        <span aria-hidden>{favorited ? "★" : "☆"}</span>
      </button>
    );
  }

  return (
    <button
      {...common}
      className={`tap relative z-20 -m-1 shrink-0 rounded-sm p-1 text-[15px] leading-none transition-colors ${
        favorited ? "text-signal" : "text-faint hover:text-dim"
      }`}
    >
      <span aria-hidden>{favorited ? "★" : "☆"}</span>
    </button>
  );
}
