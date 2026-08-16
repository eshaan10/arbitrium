import { americanStr, impliedFromAmerican } from "@/lib/format";
import type { Outcome } from "@/lib/types";

/**
 * Every book's raw American odds. "9 books agree" is a claim the reader should
 * be able to audit, so the nine named prices are here rather than only the
 * count. Odds are RAW — vig included — because that is what you would actually
 * be quoted; the vig-stripped number is the consensus probability elsewhere.
 */
export function BooksTable({ outcomes }: { outcomes: Outcome[] }) {
  const rows = outcomes.filter((o) => o.books && Object.keys(o.books).length > 0);
  if (rows.length === 0) return null;

  const allBooks = [...new Set(rows.flatMap((o) => Object.keys(o.books!)))].sort();

  // Best price for an outcome = lowest implied probability, i.e. the most
  // generous line for that side.
  const best: Record<string, string | null> = {};
  for (const o of rows) {
    let bk: string | null = null;
    let bp = Infinity;
    for (const [book, v] of Object.entries(o.books!)) {
      const ip = impliedFromAmerican(v);
      if (ip < bp) {
        bp = ip;
        bk = book;
      }
    }
    best[o.team ?? ""] = bk;
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] border-collapse text-meta">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="py-2 pr-3 font-medium text-muted">Book</th>
              {rows.map((o) => (
                <th key={o.team} className="py-2 pr-3 font-medium text-dim">
                  {o.team}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {allBooks.map((b) => (
              <tr key={b} className="border-b border-[var(--surface-raised)]">
                <td className="py-1.5 pr-3 text-dim">{b}</td>
                {rows.map((o) => {
                  const v = o.books![b];
                  if (v == null) {
                    return (
                      <td key={o.team} className="tabular py-1.5 pr-3 text-faint">
                        —
                      </td>
                    );
                  }
                  const isBest = best[o.team ?? ""] === b;
                  return (
                    <td
                      key={o.team}
                      title={`${(impliedFromAmerican(v) * 100).toFixed(1)}% implied`}
                      className={`tabular py-1.5 pr-3 ${isBest ? "text-signal" : "text-text"}`}
                    >
                      {americanStr(v)}
                      {isBest ? " ★" : ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-micro text-faint">
        ★ = best available price for that outcome. Raw American odds, vig included.
      </p>
    </div>
  );
}
