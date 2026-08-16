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
 * Which section an event belongs to, relative to a supplied `now`.
 *
 * `now` is a parameter rather than a call to Date.now() inside here because
 * grouping decides DOM STRUCTURE — an event straddling midnight would land in
 * a different section on the server than in the browser, and a structural
 * hydration mismatch cannot be papered over with suppressHydrationWarning. The
 * caller passes the server's clock for the first paint and the browser's clock
 * after mount, so both renders agree.
 */
export function groupFor(scheduledStart: string, now: number): GroupKey {
  const kickoff = new Date(scheduledStart).getTime();
  if (Number.isNaN(kickoff)) return "later";
  if (kickoff <= now) return "started";

  const end = new Date(now);
  end.setHours(23, 59, 59, 999);
  if (kickoff <= end.getTime()) return "today";

  const week = new Date(now);
  week.setDate(week.getDate() + 7);
  week.setHours(23, 59, 59, 999);
  if (kickoff <= week.getTime()) return "week";

  return "later";
}

export interface Group {
  key: GroupKey;
  label: string;
  events: Divergence[];
}

/** Groups in fixed order, with empty sections dropped. */
export function groupEvents(events: Divergence[], now: number): Group[] {
  const buckets = new Map<GroupKey, Divergence[]>();
  for (const e of events) {
    const key = groupFor(e.scheduled_start, now);
    buckets.set(key, [...(buckets.get(key) ?? []), e]);
  }
  return GROUP_ORDER.filter((k) => (buckets.get(k)?.length ?? 0) > 0).map((key) => ({
    key,
    label: GROUP_LABELS[key],
    events: buckets.get(key)!,
  }));
}
