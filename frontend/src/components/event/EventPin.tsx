"use client";

import { useFavoriteGames } from "@/lib/storage";
import { FavoriteGameButton } from "./FavoriteGameButton";

/**
 * The detail page's own pin control.
 *
 * Client-side because the pinned set lives in localStorage, which the server
 * cannot know. Renders nothing until storage has been read, so the server and
 * the first client pass agree rather than flashing an empty star into a filled
 * one.
 */
export function EventPin({
  eventId,
  label,
  rec,
}: {
  eventId: string;
  label: string;
  /** The call live right now, stored with the pin so it can be graded later. */
  rec: string | null;
}) {
  const { isFavoriteGame, toggleFavoriteGame, ready } = useFavoriteGames();

  if (!ready) return null;

  return (
    <FavoriteGameButton
      label={label}
      favorited={isFavoriteGame(eventId)}
      onToggle={() => toggleFavoriteGame(eventId, rec)}
    />
  );
}
