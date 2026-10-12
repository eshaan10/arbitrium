import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Scoreboard } from "./Scoreboard";
import type { Live } from "@/lib/types";

// Thu Oct 15, 8:15 PM ET; "now" is Sun Oct 11, 4:00 PM UTC.
const KICKOFF = "2026-10-16T00:15:00Z";
const NOW = new Date("2026-10-11T16:00:00Z");

function render(live: Live | null): string {
  return renderToStaticMarkup(
    <Scoreboard
      home_team="Denver Broncos"
      away_team="Seattle Seahawks"
      scheduled_start={KICKOFF}
      sport="nfl"
      live={live}
    />,
  );
}

function scheduled(extra: Partial<Live>): Live {
  return {
    status: "scheduled",
    period: null,
    clock: null,
    detail: null,
    home_score: null,
    away_score: null,
    home_record: null,
    away_record: null,
    venue: null,
    broadcast: null,
    possession_side: null,
    down_distance: null,
    last_play: null,
    linescore: null,
    updated_at: "2026-10-11T15:00:00Z",
    ...extra,
  };
}

describe("Scoreboard, scheduled", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("renders from the event alone when there is no live state", () => {
    const html = render(null);
    expect(html).toContain("Scheduled");
    expect(html).toContain("Seahawks");
    expect(html).toContain("Broncos");
    expect(html).toContain("sea.png");
    expect(html).toContain("den.png");
    expect(html).toContain("Oct 15");
    expect(html).toContain("starts in 4d 8h");
    expect(html).not.toContain("TV:");
  });

  it("adds records, venue and TV only when present", () => {
    const html = render(
      scheduled({
        away_record: "4-1",
        home_record: "3-2",
        venue: "Empower Field at Mile High",
        broadcast: "Prime Video",
      }),
    );
    expect(html).toContain("4-1");
    expect(html).toContain("3-2");
    expect(html).toContain("Empower Field at Mile High");
    expect(html).toContain("TV: Prime Video");
  });
});
