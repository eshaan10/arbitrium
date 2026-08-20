import { pct } from "@/lib/format";
import { teamVisual } from "@/lib/teams";
import { SectionHeading, Card } from "@/components/primitives";
import { KickoffTime } from "./KickoffTime";
import { PriceHistory } from "./PriceHistory";
import type { ClosingPrice, EventHistory, EventRecord } from "@/lib/types";

/**
 * The detail view for a game that has left the live feed.
 *
 * A deep link has to keep working after kickoff — that is the whole point of a
 * finished-games view — but a finished game must not be dressed up as a live
 * one. There is no divergence, no edge and no recommendation here, because the
 * backend deliberately declines to score an event nobody can trade. What is
 * left is what was actually recorded: the result, and the last price each
 * source published before the game started.
 */

function Result({ e }: { e: EventRecord }) {
  const home = teamVisual(e.home_team)?.short ?? e.home_team;
  const away = teamVisual(e.away_team)?.short ?? e.away_team;
  const haveScore = e.home_score != null && e.away_score != null;
  const drawn = haveScore && e.home_score === e.away_score;

  if (e.unresolvable_reason) {
    return (
      <Card className="p-4">
        <div className="text-headline text-warn">No result recorded</div>
        <p className="prose mt-1.5 max-w-prose text-meta leading-relaxed text-muted">
          The scoreboard window closed before this outcome could be collected (
          {e.unresolvable_reason}). The scores feed only reaches back three days, so this result is
          gone permanently — it is recorded as unknown rather than guessed at.
        </p>
      </Card>
    );
  }

  if (e.status !== "final") {
    return (
      <Card className="p-4">
        <div className="text-headline text-muted">Under way</div>
        <p className="prose mt-1.5 max-w-prose text-meta leading-relaxed text-muted">
          This game has started, so it is no longer scored — a price mid-game is not something this
          system measures. The result will appear here once it is collected.
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-4">
      {haveScore ? (
        <div className="tabular flex items-baseline gap-3 text-display font-semibold">
          <span className={e.winner_team === e.away_team ? "text-text" : "text-muted"}>
            {away} {e.away_score}
          </span>
          <span className="text-meta font-normal text-faint">·</span>
          <span className={e.winner_team === e.home_team ? "text-text" : "text-muted"}>
            {home} {e.home_score}
          </span>
        </div>
      ) : (
        <div className="text-headline text-muted">Final</div>
      )}
      <p className="mt-1.5 text-meta text-muted">
        {drawn && e.winner_team == null
          ? "A draw — neither side won, which is a result in its own right and not a loss for either."
          : e.winner_team
            ? `${teamVisual(e.winner_team)?.short ?? e.winner_team} won.`
            : "Finished, but no winner was recorded."}
        {e.resolution_source ? ` Source: ${e.resolution_source.replace(/_/g, " ")}.` : ""}
      </p>
    </Card>
  );
}

function ClosingTable({ closing }: { closing: ClosingPrice[] }) {
  const teams = [...new Set(closing.map((c) => c.team))];

  return (
    <Card className="px-4 py-1">
      {teams.map((team) => {
        const rows = closing.filter((c) => c.team === team);
        return (
          <div key={team ?? "draw"} className="border-b border-border py-3 last:border-b-0">
            <div className="text-body text-text">{teamVisual(team)?.short ?? team ?? "Draw"}</div>
            <div className="mt-1.5 space-y-1">
              {rows.map((r) => (
                <div key={r.source} className="flex items-baseline justify-between gap-4">
                  <span className="text-meta capitalize text-muted">{r.source}</span>
                  <span className="flex items-baseline gap-2">
                    <span className="tabular text-body text-text">
                      {pct(r.implied_probability, 1)}
                    </span>
                    {/* When the last change was recorded. Often well before
                        kickoff: the dedup trigger stores only genuine moves, so
                        a price set days earlier means it never moved again. */}
                    <KickoffTime iso={r.snapshot_time} className="text-micro text-faint" />
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </Card>
  );
}

export function FinishedEvent({
  event,
  closing,
  history,
}: {
  event: EventRecord;
  closing: ClosingPrice[] | null;
  history: EventHistory | null;
}) {
  const teams = [...new Set((closing ?? []).map((c) => c.team))];

  return (
    <div className="space-y-5">
      <Result e={event} />

      <div>
        <SectionHeading note="The last price each source recorded at or before kickoff. An observation, not a re-scored quote — a finished game is never re-priced.">
          Closing prices
        </SectionHeading>
        {closing && closing.length > 0 ? (
          <ClosingTable closing={closing} />
        ) : (
          <p className="prose text-meta leading-relaxed text-muted">
            No price was recorded for this game before it started, so there is no closing line to
            show.
          </p>
        )}
      </div>

      {history && teams.length > 0 ? (
        <div>
          <SectionHeading note="Everything recorded for this event, including any ticks after kickoff.">
            Price history
          </SectionHeading>
          <div className="space-y-4">
            {teams.map((team) => (
              <Card key={team ?? "draw"} className="p-4">
                <div className="mb-2 text-body text-text">
                  {teamVisual(team)?.short ?? team ?? "Draw"}
                </div>
                <PriceHistory history={history} team={team} />
              </Card>
            ))}
          </div>
        </div>
      ) : null}

      <p className="prose max-w-[64ch] text-micro leading-relaxed text-faint">
        No divergence, edge or recommendation is shown for a finished game. Those numbers describe a
        bet that can still be placed, and re-computing them from stale quotes would produce a
        confident-looking figure for a trade that no longer exists.
      </p>
    </div>
  );
}
