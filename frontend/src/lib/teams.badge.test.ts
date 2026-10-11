/**
 * The initials badge stands in for a missing logo, so it has to be legible:
 * every colour it can draw is held to 4.5:1 (body text) against the badge fill,
 * read from the stylesheet that ships rather than from a copy.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { contrast } from "./color";
import { BADGE_COLORS, badgeColor } from "./teams";

const css = readFileSync(join(__dirname, "../app/globals.css"), "utf8");
const RAISED = css.match(/--surface-raised:\s*(#[0-9a-fA-F]{6})/)![1];

describe("initials badge", () => {
  it.each(BADGE_COLORS)("%s clears 4.5:1 on --surface-raised", (color) => {
    expect(contrast(color, RAISED)).toBeGreaterThanOrEqual(4.5);
  });

  it("gives a team the same colour every time", () => {
    expect(badgeColor("Seattle Kraken")).toBe(badgeColor("Seattle Kraken"));
    expect(BADGE_COLORS).toContain(badgeColor("Seattle Kraken"));
  });

  it("still returns a colour for a missing name", () => {
    expect(BADGE_COLORS).toContain(badgeColor(null));
  });
});
