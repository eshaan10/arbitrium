import { REFERENCE_TIME_ZONE } from "./format";
import type { Divergence } from "./types";

export type GroupKey = "today" | "week" | "later" | "started";

export const GROUP_LABELS: Record<GroupKey, string> = {
  started: "In progress or past",
  today: "Today",
  week: "This week",
  later: "Later",
};

export const GROUP_ORDER: GroupKey[] = ["started", "today", "week", "later"];

/**
 * The calendar day an instant falls on, in an EXPLICIT timezone.
 *
 * Returned as a "YYYY-MM-DD" string and compared as such, so no offset
 * arithmetic is needed and daylight-saving transitions cannot shift a boundary.
 */
function dayKey(ms: number, timeZone: string): string {
  // en-CA formats as ISO-like YYYY-MM-DD, which sorts and subtracts cleanly.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(ms));
}

/** Whole days from `a` to `b`, both "YYYY-MM-DD" in the same zone. */
function daysBetween(a: string, b: string): number {
  const parse = (s: string) => {
    const [y, m, d] = s.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((parse(b) - parse(a)) / 86_400_000);
}

/**
 * Which section an event belongs to, relative to a supplied `now`.
 *
 * TWO things have to be pinned for this to be stable, and only one of them
 * used to be.
 *
 * `now` is a parameter rather than a call to Date.now() in here because
 * grouping decides DOM STRUCTURE — a structural hydration mismatch cannot be
 * papered over with suppressHydrationWarning.
 *
 * But passing the same `now` was not enough, and this genuinely broke: the day
 * boundary was computed with `setHours(23,59,59,999)`, which uses whatever
 * timezone the RUNTIME is in. The server runs in UTC and the browser in the
 * reader's own zone, so the same instant fell on different calendar days and an
 * evening game was rendered under "This week" by the server and "Today" by the
 * browser — React threw a hydration error and regenerated the tree.
 *
 * So the zone is explicit too, and defaults to the same reference zone the
 * kickoff timestamps use before mount. Grouping is therefore identical in every
 * runtime — no reshuffle after hydration, which for section headings would be a
 * visible layout jump rather than a quiet correction.
 */
export function groupFor(
  scheduledStart: string,
  now: number,
  timeZone: string = REFERENCE_TIME_ZONE,
): GroupKey {
  const kickoff = new Date(scheduledStart).getTime();
  if (Number.isNaN(kickoff)) return "later";
  if (kickoff <= now) return "started";

  const today = dayKey(now, timeZone);
  const day = dayKey(kickoff, timeZone);
  const delta = daysBetween(today, day);

  if (delta <= 0) return "today";
  if (delta <= 7) return "week";
  return "later";
}

export interface Group {
  key: GroupKey;
  label: string;
  events: Divergence[];
}

/** Groups in fixed order, with empty sections dropped. */
export function groupEvents(
  events: Divergence[],
  now: number,
  timeZone: string = REFERENCE_TIME_ZONE,
): Group[] {
  const buckets = new Map<GroupKey, Divergence[]>();
  for (const e of events) {
    const key = groupFor(e.scheduled_start, now, timeZone);
    buckets.set(key, [...(buckets.get(key) ?? []), e]);
  }
  return GROUP_ORDER.filter((k) => (buckets.get(k)?.length ?? 0) > 0).map((key) => ({
    key,
    label: GROUP_LABELS[key],
    events: buckets.get(key)!,
  }));
}
