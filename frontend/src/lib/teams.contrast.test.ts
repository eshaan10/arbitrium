/**
 * The generated team accents must stay legible on the app background.
 *
 * This is a falsifiable monitor, not a unit test of the generator. Team brand
 * colours are third-party data: ESPN can change one at any time, and the next
 * `pnpm gen:teams` would quietly commit an accent nobody can see against
 * #0a0b0d. Measured incidence of a failure is currently zero — all 32 clear the
 * floor, with the worst at 3.21:1 — which is exactly why it is worth asserting
 * rather than assuming.
 *
 * The contrast function here is deliberately reimplemented instead of imported
 * from the generator: a test that borrows the code under test would agree with
 * it about a shared mistake.
 */

import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CONTRAST_FLOOR, TEAM_VISUALS } from "./teams.generated";

const BACKGROUND = "#0a0b0d";
const LOGO_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../../public/logos/nfl");

function relativeLuminance(hex: string): number {
  const h = hex.replace("#", "");
  const channels = [0, 2, 4].map((i) => {
    const v = parseInt(h.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const entries = Object.entries(TEAM_VISUALS);

describe("generated team visuals", () => {
  it("covers all 32 NFL teams", () => {
    expect(entries).toHaveLength(32);
  });

  it.each(entries)("%s: accent clears the contrast floor", (name, visual) => {
    const ratio = contrastRatio(visual.accent, BACKGROUND);
    expect(
      ratio,
      `${name} accent ${visual.accent} is ${ratio.toFixed(2)}:1 against ${BACKGROUND}, ` +
        `below the ${CONTRAST_FLOOR}:1 floor. Its raw brand colour is ${visual.raw}. ` +
        `Re-run \`pnpm gen:teams\`; if it still fails, the lift in ` +
        `scripts/generate-teams.mjs can no longer reach the floor for this hue.`,
    ).toBeGreaterThanOrEqual(CONTRAST_FLOOR);
  });

  it.each(entries)("%s: alternate accent clears the floor too", (name, visual) => {
    // The alternate is what breaks a home/away collision, so it is real UI and
    // has to be as legible as the primary.
    expect(contrastRatio(visual.alt, BACKGROUND)).toBeGreaterThanOrEqual(CONTRAST_FLOOR);
  });

  it.each(entries)("%s: logo asset is vendored", (name, visual) => {
    // Logos are committed to public/, not hotlinked. A team whose abbreviation
    // changes upstream (the WAS -> wsh case) shows up here as a missing file
    // rather than as a blank square in production.
    expect(
      existsSync(resolve(LOGO_DIR, `${visual.abbr}.png`)),
      `Missing logo for ${name}: public/logos/nfl/${visual.abbr}.png`,
    ).toBe(true);
  });

  it("assigns every team a distinct accent, or a working fallback", () => {
    // Three teams share #002a5c upstream (Dallas, New England, Seattle) and two
    // share #000000 (Raiders, Steelers). They are allowed to collide, but each
    // colliding team MUST have an alternate that differs from its accent —
    // that alternate is the only thing that keeps a head-to-head card from
    // drawing two identical bars.
    const byAccent = new Map<string, string[]>();
    for (const [name, v] of entries) {
      byAccent.set(v.accent, [...(byAccent.get(v.accent) ?? []), name]);
    }
    for (const [accent, names] of byAccent) {
      if (names.length === 1) continue;
      for (const name of names) {
        expect(
          TEAM_VISUALS[name].alt,
          `${name} shares accent ${accent} with ${names.filter((n) => n !== name).join(", ")} ` +
            `but has no distinct alternate to fall back on`,
        ).not.toBe(accent);
      }
    }
  });
});
