import { formatCentsDelta, type NetMove } from "@/lib/moves";
import { teamVisual } from "@/lib/teams";

/**
 * "▲ 2.4¢ · 24h" — self-explanatory in three tokens.
 *
 * Replaces the unlabelled hover sparkline. It says which direction, how far,
 * over what window, and (in the title) for which side and across how many
 * recorded changes. No axis needed because there is no chart to read.
 */
export function MoveChip({ move, hours = 24 }: { move: NetMove; hours?: number }) {
  const up = move.delta > 0;
  const short = teamVisual(move.team)?.short ?? move.team;

  return (
    <span
      className="tabular inline-flex items-center gap-1 rounded-full border border-border px-1.5 py-[2px] text-micro"
      style={{ color: up ? "var(--gain)" : "var(--loss)" }}
      title={
        `${short} moved ${up ? "up" : "down"} ${formatCentsDelta(move.delta)}¢ on Kalshi over the ` +
        `last ${hours}h, across ${move.changes} recorded price ${
          move.changes === 1 ? "change" : "changes"
        }. Net of the whole window, not the sum of every tick.`
      }
    >
      <span aria-hidden>{up ? "▲" : "▼"}</span>
      {formatCentsDelta(move.delta)}¢
      <span className="text-faint">{hours}h</span>
    </span>
  );
}
