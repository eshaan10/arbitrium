"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchEventsLookup, queryKeys } from "@/lib/api";
import { teamVisual } from "@/lib/teams";
import { KickoffTime } from "@/components/event/KickoffTime";
import type { PinnedGame } from "@/lib/storage";
import type { EventRecord } from "@/lib/types";

/**
 * Pinned games that have left the live feed.
 *
 * /divergences only scores scheduled events, so a pinned matchup vanishes the
 * moment it kicks off. These are fetched by id from /events/lookup instead, and
 * graded against what was actually recorded.
 *
 * The grading is deliberately narrow. It reports one of exactly four verdicts,
 * and refuses to produce a fifth:
 *
 *   right / wrong  — a call existed AND a winner was recorded
 *   push           — the game was a draw, so the call was neither
 *   ungraded       — no call existed when you pinned it, or no winner was ever
 *                    recorded (including games whose result window closed)
 *
 * Nothing here is aggregated into a hit rate. A handful of self-selected pins
 * is not a track record, and presenting it as one would be exactly the kind of
 * number the /performance page refuses to publish.
 */
type Verdict = "right" | "wrong" | "push" | "ungraded";

interface Graded {
  event: EventRecord;
  pin: PinnedGame;
  verdict: Verdict;
  detail: string;
}

function parseRec(rec: string | null): { side: string; team: string } | null {
  if (!rec) return null;
  const i = rec.indexOf("|");
  if (i < 0) return null;
  return { side: rec.slice(0, i), team: rec.slice(i + 1) };
}

function grade(event: EventRecord, pin: PinnedGame): Graded {
  const call = parseRec(pin.rec);

  if (!call) {
    return {
      event,
      pin,
      verdict: "ungraded",
      detail:
        pin.at === ""
          ? "Pinned before this app recorded what the call was, so there is nothing to grade it against."
          : "There was no recommendation on this game when you pinned it.",
    };
  }

  if (event.unresolvable_reason) {
    return {
      event,
      pin,
      verdict: "ungraded",
      detail: `The result was never collected (${event.unresolvable_reason}), so this can't be graded.`,
    };
  }

  if (event.status !== "final") {
    return { event, pin, verdict: "ungraded", detail: "Not resolved yet." };
  }

  // A recorded final with no winner is a draw, not a loss.
  if (event.winner_team == null) {
    const drawn =
      event.home_score != null && event.away_score != null && event.home_score === event.away_score;
    return {
      event,
      pin,
      verdict: drawn ? "push" : "ungraded",
      detail: drawn
        ? "The game was a draw, so the call was neither right nor wrong."
        : "Finished, but no winner was recorded — nothing to grade against.",
    };
  }

  // "yes <team>" wins if that team won; "no <team>" wins if they did not.
  const teamWon = event.winner_team === call.team;
  const correct = call.side === "yes" ? teamWon : !teamWon;
  const short = teamVisual(call.team)?.short ?? call.team;

  return {
    event,
    pin,
    verdict: correct ? "right" : "wrong",
    detail: `You pinned "Buy ${call.side} ${short}". ${
      teamVisual(event.winner_team)?.short ?? event.winner_team
    } won.`,
  };
}

const VERDICT_STYLE: Record<Verdict, { label: string; color: string }> = {
  right: { label: "Called it", color: "var(--status-ok)" },
  wrong: { label: "Missed", color: "var(--loss)" },
  push: { label: "Push", color: "var(--muted)" },
  ungraded: { label: "Not graded", color: "var(--faint)" },
};

function PastRow({ g }: { g: Graded }) {
  const style = VERDICT_STYLE[g.verdict];
  const away = teamVisual(g.event.away_team)?.short ?? g.event.away_team;
  const home = teamVisual(g.event.home_team)?.short ?? g.event.home_team;
  const score =
    g.event.home_score != null && g.event.away_score != null
      ? `${g.event.away_score}–${g.event.home_score}`
      : null;

  return (
    <Link
      href={`/events/${g.event.event_id}`}
      className="block rounded-md border border-border bg-surface p-3.5 transition-colors hover:border-border-lit"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-title font-medium text-text">
          {away} <span className="font-normal text-muted">@</span> {home}
        </span>
        <span className="flex items-center gap-2">
          {score ? <span className="tabular text-meta text-dim">{score}</span> : null}
          <span
            className="label rounded-sm border px-1.5 py-[2px] text-micro"
            style={{ color: style.color, borderColor: style.color }}
          >
            {style.label}
          </span>
        </span>
      </div>
      <p className="mt-1.5 text-meta text-muted">{g.detail}</p>
      <KickoffTime iso={g.event.scheduled_start} className="mt-1 block text-micro text-faint" />
    </Link>
  );
}

export function PastGames({ pins }: { pins: PinnedGame[] }) {
  const ids = pins.map((p) => p.id);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.lookup(ids),
    queryFn: () => fetchEventsLookup(ids),
    enabled: ids.length > 0,
    staleTime: 5 * 60_000,
  });

  if (ids.length === 0) return null;
  if (isLoading) {
    return <p className="text-meta text-faint">Looking up finished games…</p>;
  }
  if (!data) return null;

  const byId = new Map(data.events.map((e) => [e.event_id, e]));
  const graded = pins
    .map((pin) => {
      const event = byId.get(pin.id);
      // A pin whose event the backend no longer has is dropped rather than
      // rendered as an empty row — there is genuinely nothing to say about it.
      return event && event.status !== "scheduled" ? grade(event, pin) : null;
    })
    .filter((g): g is Graded => g !== null)
    .sort(
      (a, b) =>
        new Date(b.event.scheduled_start).getTime() - new Date(a.event.scheduled_start).getTime(),
    );

  if (graded.length === 0) return null;

  return (
    <section>
      <h2 className="rule-label mb-3 flex items-center gap-3 label text-meta font-semibold text-dim">
        Finished
        <span className="tabular text-micro font-normal text-faint">{graded.length}</span>
      </h2>
      <div className="grid gap-2.5 lg:grid-cols-2">
        {graded.map((g) => (
          <PastRow key={g.event.event_id} g={g} />
        ))}
      </div>
      <p className="mt-3 max-w-[64ch] text-micro leading-relaxed text-faint">
        These are the games you pinned, graded against the call that was live when you pinned them.
        They are not a track record — a handful of self-selected games cannot support a hit rate,
        and no rate is computed from them. The{" "}
        <Link href="/performance" className="text-muted underline-offset-2 hover:underline">
          performance page
        </Link>{" "}
        grades the system properly, with a sample gate.
      </p>
    </section>
  );
}
