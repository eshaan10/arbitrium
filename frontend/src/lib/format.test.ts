import { afterEach, describe, expect, it } from "vitest";
import { fairValueCents, kickoff, kickoffFixed, timeToKickoffLong } from "./format";

/**
 * A falsifiable monitor for the kickoff hydration bug.
 *
 * `kickoff` used to format in the platform's own timezone. The server ran in
 * UTC and the browser in the viewer's zone, so the same game rendered as
 * "Sep 13 · 8:25 PM" on the server and "Sep 13 · 1:25 PM" in a Pacific browser
 * — a seven-hour disagreement about when a game starts, surfacing as a React
 * hydration mismatch. The server literally cannot know the browser's zone, so
 * the first render is pinned to a fixed one and `KickoffTime` swaps to the
 * viewer's after mount.
 *
 * These tests move the ambient zone around underneath the formatter. If anyone
 * reverts to platform-default formatting, the fixed-zone assertions stop
 * holding on every machine that isn't already in Eastern.
 */

const KICKOFF = "2026-09-14T00:25:00Z"; // 8:25 PM EDT / 5:25 PM PDT
const ORIGINAL_TZ = process.env.TZ;

function underZone<T>(tz: string, fn: () => T): T {
  process.env.TZ = tz;
  return fn();
}

afterEach(() => {
  process.env.TZ = ORIGINAL_TZ;
});

describe("kickoffFixed", () => {
  it("returns the same string regardless of the machine's timezone", () => {
    const zones = ["UTC", "America/Los_Angeles", "Australia/Sydney", "Europe/London"];

    // Guard: prove the harness actually moves the ambient zone. Without this
    // the assertion below would pass trivially if TZ mutation stopped taking
    // effect, and the monitor would quietly stop monitoring anything.
    const ambient = zones.map((tz) => underZone(tz, () => kickoff(KICKOFF)));
    expect(new Set(ambient).size).toBeGreaterThan(1);

    const rendered = zones.map((tz) => underZone(tz, () => kickoffFixed(KICKOFF)));
    expect(new Set(rendered).size).toBe(1);
  });

  it("renders the Eastern time, labelled", () => {
    expect(underZone("UTC", () => kickoffFixed(KICKOFF))).toBe("Sep 13 · 8:25 PM EDT");
  });

  it("always carries a zone label, so the post-mount swap is never ambiguous", () => {
    // The pre-mount and post-mount renders deliberately show different clock
    // times. Without a label a reader cannot tell which one they are seeing.
    const local = underZone("America/Los_Angeles", () =>
      kickoff(KICKOFF, { locale: "en-US", timeZone: "America/Los_Angeles" }),
    );
    expect(local).toBe("Sep 13 · 5:25 PM PDT");
    expect(kickoffFixed(KICKOFF)).toMatch(/E[SD]T$/);
  });

  it("honours an explicit zone rather than the ambient one", () => {
    const sydney = underZone("UTC", () =>
      kickoff(KICKOFF, { locale: "en-US", timeZone: "Australia/Sydney" }),
    );
    // Same instant, next calendar day on the other side of the dateline.
    expect(sydney).toContain("Sep 14");
  });

  it("returns a dash for a missing or unparseable timestamp", () => {
    expect(kickoffFixed(null)).toBe("—");
    expect(kickoffFixed("not a date")).toBe("—");
  });
});

describe("the card's date line", () => {
  it("joins date and time with a comma when asked", () => {
    expect(kickoffFixed(KICKOFF, ", ")).toBe("Sep 13, 8:25 PM EDT");
  });

  it.each([
    [4 * 86_400_000 + 3_600_000, "in 4 days"],
    [86_400_000, "in 24 hours"],
    [3_600_000, "in 1 hour"],
    [5 * 3_600_000, "in 5 hours"],
    [12 * 60_000, "in 12 minutes"],
    [20_000, "in 1 minute"],
    [0, "started"],
    [-60_000, "started"],
  ])("spells %ims to kickoff as %j", (ahead, text) => {
    const now = new Date(KICKOFF).getTime() - ahead;
    expect(timeToKickoffLong(KICKOFF, now)).toBe(text);
  });
});

describe("fair value beside a price", () => {
  it("shows whole cents when the two differ by a cent or more", () => {
    expect(fairValueCents(0.4, 0.39)).toBe("40¢");
  });
  it("shows one decimal when they would round to the same cent", () => {
    expect(fairValueCents(0.2141, 0.21)).toBe("21.4¢");
    expect(fairValueCents(0.21, 0.21)).toBe("21.0¢");
  });
  it("is a dash when missing", () => {
    expect(fairValueCents(null, 0.21)).toBe("—");
  });
});
