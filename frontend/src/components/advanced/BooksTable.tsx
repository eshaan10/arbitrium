import { americanStr, impliedFromAmerican } from "@/lib/format";
import type { Outcome } from "@/lib/types";

/**
 * Every book's raw American odds. "9 books agree" is a claim the reader should
 * be able to audit, so the nine named prices are here rather than only the
 * count. Odds are RAW — vig included — because that is what you would actually
 * be quoted; the vig-stripped number is the consensus probability elsewhere.
 *
 * TWO layouts, not one shrunk down. A matrix of book × outcome is the right
 * shape on a wide screen — it lets you scan a column and see which book is out
 * of line — but on a phone that same table is either scrolled sideways (so the
 * book name leaves the screen, and a price with no name is useless) or squeezed
 * until nothing is readable. Below `sm` each book becomes its own row with its
 * outcomes stacked beneath it, which keeps every price attached to the name it
 * belongs to. Same data, same ★ marks, same ordering.
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

  const isBest = (o: Outcome, book: string) => best[o.team ?? ""] === book;

  return (
    <div>
      {/* --- phone: one block per book -------------------------------------- */}
      <ul className="divide-y divide-border sm:hidden">
        {allBooks.map((b) => (
          <li key={b} className="py-2 first:pt-0 last:pb-0">
            <div className="text-meta text-dim">{b}</div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              {rows.map((o) => {
                const v = o.books![b];
                return (
                  <span key={o.team} className="flex items-baseline gap-1.5">
                    <span className="text-micro text-muted">{o.team}</span>
                    <span
                      className={`tabular text-meta ${
                        v == null ? "text-faint" : isBest(o, b) ? "text-signal" : "text-text"
                      }`}
                    >
                      {v == null ? "—" : americanStr(v)}
                      {v != null && isBest(o, b) ? " ★" : ""}
                    </span>
                  </span>
                );
              })}
            </div>
          </li>
        ))}
      </ul>

      {/* --- wide: the matrix ----------------------------------------------- */}
      <div className="scroll-x hidden sm:block">
        <table className="w-full min-w-[420px] border-collapse text-meta">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="label py-2 pr-3 text-micro font-medium text-muted">Book</th>
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
                  return (
                    <td
                      key={o.team}
                      title={`${(impliedFromAmerican(v) * 100).toFixed(1)}% implied`}
                      className={`tabular py-1.5 pr-3 ${isBest(o, b) ? "text-signal" : "text-text"}`}
                    >
                      {americanStr(v)}
                      {isBest(o, b) ? " ★" : ""}
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
