import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FinalRow } from "./FinalRow";
import { final } from "@/lib/finals.fixture";
import type { FinalGame } from "@/lib/types";

function render(f: FinalGame, open = false): string {
  return renderToStaticMarkup(<FinalRow f={f} open={open} onToggle={() => {}} />);
}

/** Visible text only: titles and aria-labels are not what a reader sees. */
function text(html: string): string {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ");
}

describe("FinalRow, collapsed", () => {
  it("keeps the pick headline and shows the final score and a hit badge", () => {
    const t = text(render(final()));
    expect(t).toContain("Ravens to lose");
    expect(t).toContain("Final · 15–23");
    expect(t).toContain("Pick hit");
    expect(t).not.toContain("Pick missed");
  });

  it("shows a missed badge for a missed pick", () => {
    const t = text(render(final({ pick_result: "miss" })));
    expect(t).toContain("Pick missed");
    expect(t).not.toContain("Pick hit");
  });

  it("shows the flagged snapshot as pregame, never a Buy order", () => {
    const t = text(render(final()));
    expect(t).toContain("pregame");
    expect(t).toContain("No at 54¢");
    expect(t).toContain("Books 61¢");
    expect(t).not.toMatch(/Buy (Yes|No)/);
  });

  it("has no badge when pick_result is null", () => {
    const t = text(render(final({ pick_result: null })));
    expect(t).not.toMatch(/Pick (hit|missed)/);
  });

  it("still shows the final score for a game with no flagged pick", () => {
    const t = text(render(final({ flagged: null, pick_result: null })));
    expect(t).toContain("Final · 15–23");
    expect(t).toContain("Falcons won");
    expect(t).not.toContain("pregame");
    expect(t).not.toMatch(/Pick (hit|missed)/);
  });
});

describe("FinalRow, expanded", () => {
  it("shows the final scoreboard and the We said line, and no bet calculator", () => {
    const t = text(render(final(), true));
    expect(t).toContain("Final");
    expect(t).toContain(
      "We said: Ravens to lose at 54¢ (books 61¢). Result: Ravens lost 15-23. Pick hit.",
    );
    expect(render(final(), true)).not.toMatch(/Your bet|Bet amount|Stake in dollars/);
  });

  it("has no We said line without a flagged pick", () => {
    const t = text(render(final({ flagged: null, pick_result: null }), true));
    expect(t).not.toContain("We said");
    expect(t).toContain("Final");
  });
});
