"use client";

import { kickoff, kickoffFixed } from "@/lib/format";
import { useIsClient } from "@/lib/useIsClient";

/**
 * A kickoff timestamp that is correct for the reader and identical across the
 * server/hydration boundary.
 *
 * The server cannot know the browser's timezone. Formatting with the platform
 * default meant the server rendered a UTC-derived time and the browser rendered
 * a local one — "Sep 13 · 8:25 PM" against "Sep 13 · 1:25 PM", a seven-hour
 * disagreement about when a game starts, reported by React as a hydration
 * mismatch. Suppressing that warning would have kept the wrong time.
 *
 * So the first render — server AND hydration — uses a FIXED locale and zone,
 * which makes the two passes equal by construction rather than by luck.
 * `useIsClient` flips only after mount, and React re-renders with the viewer's
 * own zone. Both forms carry a zone label, so the swap reads as a correction
 * rather than a glitch.
 */
export function KickoffTime({
  iso,
  className,
}: {
  iso: string | null | undefined;
  className?: string;
}) {
  const isClient = useIsClient();
  return <span className={className}>{isClient ? kickoff(iso) : kickoffFixed(iso)}</span>;
}
