/**
 * Generates src/lib/teams.generated.ts and downloads team logos into
 * public/logos/nfl/.
 *
 * Run with: pnpm gen:teams
 *
 * Why a generator and not a runtime lookup:
 *
 *  - Logos are vendored, not hotlinked. Team logos appear on every card, and a
 *    third-party CDN is not a dependency a core visual element should carry.
 *  - Team codes come from ESPN's own team list, never from the backend's
 *    reference/teams.py. The two disagree — that file has WAS, ESPN serves wsh
 *    and 404s on was — and a derived URL built from the wrong list fails for
 *    exactly one team, which is the kind of bug that ships.
 *  - Brand colours are unusable raw. 22 of 32 primaries fall under 3:1 against
 *    the app background (Houston is 1.02:1; the Raiders and Steelers are
 *    literally #000000), so each is lifted in OKLCH — lightness raised until it
 *    clears the floor, hue preserved — at generation time. The committed values
 *    are asserted by src/lib/teams.contrast.test.ts.
 */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LOGO_DIR = resolve(ROOT, "public/logos/nfl");
const OUT = resolve(ROOT, "src/lib/teams.generated.ts");

const TEAMS_URL =
  "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams?limit=40";
const logoUrl = (abbr) =>
  `https://a.espncdn.com/i/teamlogos/nfl/500/scoreboard/${abbr}.png`;

/** Contrast floor for an accent against --bg. */
export const CONTRAST_FLOOR = 3.2;
const BG = "0a0b0d";

/* --- colour maths (sRGB <-> OKLab), no dependencies ---------------------- */

const srgbToLinear = (c) => {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};

const linearToSrgb = (c) => {
  const v = Math.max(0, Math.min(1, c));
  return Math.round(255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055));
};

const hexToRgb = (hex) => [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));

function hexToOklch(hex) {
  const [r, g, b] = hexToRgb(hex).map(srgbToLinear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return { L, C: Math.hypot(a, bb), H: Math.atan2(bb, a) };
}

function oklchToHex({ L, C, H }) {
  const a = C * Math.cos(H);
  const b = C * Math.sin(H);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const bl = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  return [r, g, bl].map((c) => linearToSrgb(c).toString(16).padStart(2, "0")).join("");
}

const relLuminance = (hex) => {
  const [r, g, b] = hexToRgb(hex).map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

export function contrast(hex, against = BG) {
  const a = relLuminance(hex);
  const b = relLuminance(against);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/**
 * Raise lightness until the colour clears the floor, keeping its hue.
 *
 * Near-achromatic input (the black primaries) has no hue to preserve, so it
 * becomes a neutral grey rather than being pushed into an invented tint.
 */
export function lift(hex, floor = CONTRAST_FLOOR) {
  const { L, C, H } = hexToOklch(hex);

  // Achromatic input has no hue to preserve, so it becomes a neutral rather
  // than being pushed into an invented tint. The neutral tracks the SOURCE
  // lightness instead of collapsing to one grey: the Raiders are black and
  // silver, and flattening both to the same value left that team with an
  // alternate identical to its accent — no fallback for a head-to-head card.
  if (C < 0.02) {
    const target = Math.min(0.88, Math.max(0.62, 0.62 + L * 0.26));
    for (let step = 0; step <= 40; step += 1) {
      const candidate = oklchToHex({ L: Math.min(0.95, target + step * 0.01), C: 0, H: 0 });
      if (contrast(candidate) >= floor) return candidate;
    }
  }

  for (let step = 0; step <= 80; step += 1) {
    const candidate = oklchToHex({ L: Math.min(0.95, L + step * 0.01), C, H });
    if (contrast(candidate) >= floor) return candidate;
  }
  return oklchToHex({ L: 0.95, C, H });
}

/* --- generation ---------------------------------------------------------- */

async function main() {
  const res = await fetch(TEAMS_URL);
  if (!res.ok) throw new Error(`ESPN teams request failed: ${res.status}`);
  const payload = await res.json();
  const teams = payload.sports[0].leagues[0].teams.map((t) => t.team);

  if (teams.length !== 32) {
    throw new Error(`Expected 32 NFL teams, got ${teams.length}`);
  }

  await mkdir(LOGO_DIR, { recursive: true });

  const rows = [];
  for (const t of teams) {
    const abbr = t.abbreviation.toLowerCase();
    const url = logoUrl(abbr);
    const img = await fetch(url);
    if (!img.ok) {
      // Fail loudly. A missing logo silently degrading to a blank square is
      // how the WAS/wsh mismatch would have shipped unnoticed.
      throw new Error(`Logo 404 for ${t.displayName} (${abbr}): ${url}`);
    }
    await writeFile(resolve(LOGO_DIR, `${abbr}.png`), Buffer.from(await img.arrayBuffer()));

    const primary = (t.color || "").toLowerCase();
    const alternate = (t.alternateColor || primary).toLowerCase();
    rows.push({
      name: t.displayName,
      abbr,
      short: t.shortDisplayName,
      accent: `#${lift(primary)}`,
      alt: `#${lift(alternate)}`,
      raw: `#${primary}`,
    });
  }

  rows.sort((a, b) => a.name.localeCompare(b.name));

  const body = rows
    .map(
      (r) =>
        `  ${JSON.stringify(r.name)}: { abbr: ${JSON.stringify(r.abbr)}, ` +
        `short: ${JSON.stringify(r.short)}, accent: ${JSON.stringify(r.accent)}, ` +
        `alt: ${JSON.stringify(r.alt)}, raw: ${JSON.stringify(r.raw)} },`,
    )
    .join("\n");

  const file = `/* GENERATED by scripts/generate-teams.mjs — do not edit by hand.
 *
 * Keyed by canonical team name, which is the join key /divergences already
 * uses: all 32 names match ESPN's displayName exactly, verified against the
 * live feed.
 *
 * \`accent\` and \`alt\` are the brand colours LIFTED to clear ${CONTRAST_FLOOR}:1 against
 * --bg; \`raw\` is the untouched brand colour, kept only so a regression is
 * auditable. Asserted by teams.contrast.test.ts.
 */

export interface TeamVisual {
  abbr: string;
  short: string;
  /** Brand colour, lightness-lifted to be legible on the app background. */
  accent: string;
  /** Lifted alternate, used to break home/away collisions. */
  alt: string;
  /** Untouched brand colour. Never render this on a dark surface. */
  raw: string;
}

export const CONTRAST_FLOOR = ${CONTRAST_FLOOR};

export const TEAM_VISUALS: Record<string, TeamVisual> = {
${body}
};
`;

  await writeFile(OUT, file);
  console.log(`Wrote ${rows.length} teams -> ${OUT}`);
  console.log(`Logos -> ${LOGO_DIR}`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  await main();
}
