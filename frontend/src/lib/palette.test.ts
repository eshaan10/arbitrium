import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { contrast, deltaE, oklch, simulate } from "./color";

/**
 * A falsifiable monitor for the design system.
 *
 * This does not test a copy of the palette — it PARSES src/app/globals.css and
 * checks the values that actually ship. The distinction matters: the previous
 * system's chart colours were documented as validated and then hand-tuned
 * twice, and nothing caught it because the validator lived in a scratch file
 * that was never committed.
 *
 * What is enforced, and why each rule exists:
 *
 *  1. Text contrast. A dense dark UI is exactly where a "nice" grey quietly
 *     drops under 4.5:1.
 *  2. The confidence fade FLOOR. Fading a low-confidence row is honest only
 *     while it stays readable; past that it is a hidden row, which this product
 *     forbids outright.
 *  3. Colour-vision separation of the two chart series. They are compared by
 *     colour inside one chart, so this is the one place colour carries meaning
 *     alone — and ~8% of readers have red-green deficiency.
 *  4. No semantic channel may collapse into the accent. If "negative" and
 *     "signal" look alike, the accent stops meaning anything.
 *  5. Win and loss stay apart for colour-blind readers. Lime and red are the
 *     classic confusable pair, so they are held to the chart-series bar — and
 *     the UI never relies on that alone (signs and labels carry it too).
 *  6. Every grey stays NEUTRAL. Lime is meant to be the only saturated thing at
 *     rest on the page; a grey that picks up chroma reads as a second accent.
 */

const CSS = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");

/** Read a hex-valued custom property out of the stylesheet. */
function token(name: string): string {
  const m = CSS.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,8})\\s*;`));
  if (!m) throw new Error(`--${name} is not a hex token in globals.css`);
  return m[1];
}

function numeric(name: string): number {
  const m = CSS.match(new RegExp(`--${name}:\\s*([0-9.]+)\\s*;`));
  if (!m) throw new Error(`--${name} is not a numeric token in globals.css`);
  return Number(m[1]);
}

/** Composite a foreground over a background at the given alpha. */
function flatten(fg: string, bg: string, alpha: number): string {
  const hex = (s: string, i: number) => parseInt(s.slice(1).substr(i, 2), 16);
  const mix = (i: number) =>
    Math.round(hex(fg, i) * alpha + hex(bg, i) * (1 - alpha))
      .toString(16)
      .padStart(2, "0");
  return `#${mix(0)}${mix(2)}${mix(4)}`;
}

const BG = () => token("bg");
const SURFACE = () => token("surface");
const RAISED = () => token("surface-raised");
const SUNKEN = () => token("surface-sunken");

describe("text contrast", () => {
  // Checked on --surface-raised too: the bet box and outcome tiles set text
  // INTO the card, and that lighter surface is every step's worst case.
  it.each([
    ["text", 7],
    ["text-dim", 4.5],
    ["muted", 4.5],
  ])("--%s clears %s:1 on --bg, --surface and --surface-raised", (name, min) => {
    expect(contrast(token(name), BG())).toBeGreaterThanOrEqual(min);
    expect(contrast(token(name), SURFACE())).toBeGreaterThanOrEqual(min);
    expect(contrast(token(name), RAISED())).toBeGreaterThanOrEqual(min);
  });

  it("--faint now carries real content, so it clears 4.5 like body text", () => {
    // RULE CHANGED with the graphite theme. Amber kept --faint between 2 and
    // 4.5:1 and reserved it for punctuation. Here the tertiary step sets date
    // lines and the "in play, before fees" summary — content, not decoration —
    // so the floor is RAISED to the body-text bar rather than dropped.
    expect(contrast(token("faint"), BG())).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token("faint"), SURFACE())).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token("faint"), RAISED())).toBeGreaterThanOrEqual(4.5);
  });
});

describe("the confidence fade floor", () => {
  it("keeps a faded row readable rather than hidden", () => {
    const floor = numeric("fade-floor");
    expect(contrast(flatten(token("text-dim"), SURFACE(), floor), SURFACE())).toBeGreaterThanOrEqual(3);
    expect(contrast(flatten(token("text"), SURFACE(), floor), SURFACE())).toBeGreaterThanOrEqual(4.5);
  });
});

describe("accents are readable where they are used", () => {
  it.each([
    ["signal-500", 4.5],
    ["signal-600", 4.5],
    ["arb", 4.5],
    ["warn", 4.5],
    ["error", 4.5],
    ["status-ok", 4.5],
    ["gain", 4.5],
    ["loss", 4.5],
    ["signal-800", 3], // strokes and borders only
  ])("--%s clears %s:1 on --surface and --surface-raised", (name, min) => {
    // The win and loss figures sit on the raised outcome tiles, the error and
    // availability notes on the card — so both surfaces are checked.
    expect(contrast(token(name), SURFACE())).toBeGreaterThanOrEqual(min);
    expect(contrast(token(name), RAISED())).toBeGreaterThanOrEqual(min);
  });
});

describe("the two chart series", () => {
  const K = () => token("series-kalshi");
  const C = () => token("series-consensus");

  it("are both visible on the chart surface", () => {
    expect(contrast(K(), SUNKEN())).toBeGreaterThanOrEqual(3);
    expect(contrast(C(), SUNKEN())).toBeGreaterThanOrEqual(3);
  });

  it("stay distinguishable with normal, protan and deutan vision", () => {
    expect(deltaE(K(), C())).toBeGreaterThanOrEqual(15);
    expect(deltaE(simulate(K(), "protan"), simulate(C(), "protan"))).toBeGreaterThanOrEqual(15);
    expect(deltaE(simulate(K(), "deutan"), simulate(C(), "deutan"))).toBeGreaterThanOrEqual(15);
  });

  it("are separated by chroma as well as hue, so neither rests on hue alone", () => {
    expect(Math.abs(oklch(K()).c - oklch(C()).c)).toBeGreaterThanOrEqual(0.05);
  });
});

describe("no semantic channel collapses into the accent", () => {
  const SIGNAL = () => token("signal-500");

  it.each(["neg", "loss", "warn", "error", "status-ok"])(
    "--%s is clearly distinct from --signal-500",
    (name) => {
      expect(deltaE(token(name), SIGNAL())).toBeGreaterThanOrEqual(15);
      expect(
        deltaE(simulate(token(name), "protan"), simulate(SIGNAL(), "protan")),
      ).toBeGreaterThanOrEqual(12);
    },
  );

  it("--gain DOES share the accent family, deliberately", () => {
    // The rule is that value is lime and its absence is not. A gain that
    // failed this would mean the palette had stopped saying so.
    expect(deltaE(token("gain"), SIGNAL())).toBeLessThan(10);
  });

  it("--arb is a hotter variant of the accent, not a separate hue", () => {
    // Arbitrage IS signal, so it stays in the family; it is set apart by the
    // fenced panel, its own border and its own glow. Asserted in both
    // directions so neither drift is silent.
    expect(deltaE(token("arb"), SIGNAL())).toBeLessThan(15);
    expect(token("arb")).not.toBe(SIGNAL());
  });
});

describe("win and loss", () => {
  // NEW with the graphite theme. Amber drew a loss in grey, so there was no
  // win/loss hue pair to protect. Lime against red is the textbook
  // red-green-confusable pair, so it is held to the chart-series bar under all
  // three visions. The UI also never relies on it: every figure keeps its
  // +/− sign and its "If they win / lose" label.
  it("--gain and --loss stay apart with normal, protan and deutan vision", () => {
    const g = token("gain");
    const l = token("loss");
    expect(deltaE(g, l)).toBeGreaterThanOrEqual(15);
    expect(deltaE(simulate(g, "protan"), simulate(l, "protan"))).toBeGreaterThanOrEqual(15);
    expect(deltaE(simulate(g, "deutan"), simulate(l, "deutan"))).toBeGreaterThanOrEqual(15);
  });
});

describe("the OpenGraph image's duplicated palette", () => {
  // ImageResponse renders with no stylesheet, so those colours cannot be CSS
  // variables and are written out by hand. That is the exact shape of drift
  // this project has been bitten by before: two copies of one fact, one of
  // which gets updated. A share preview in the old palette would also be the
  // most-forwarded surface in the product.
  // Read as text rather than imported: importing the route would pull in
  // next/og and an ImageResponse runtime to check five string literals.
  const OG = readFileSync(
    join(process.cwd(), "src/app/events/[id]/opengraph-image.tsx"),
    "utf8",
  );
  const ogColour = (key: string): string => {
    const m = OG.match(new RegExp(`\\b${key}:\\s*"(#[0-9a-fA-F]{6})"`));
    if (!m) throw new Error(`PALETTE.${key} is missing from the OpenGraph image`);
    return m[1];
  };

  it.each([
    ["bg", "bg"],
    ["text", "text"],
    ["dim", "text-dim"],
    ["muted", "muted"],
    ["faint", "faint"],
    ["border", "border"],
    ["signal", "signal-500"],
  ])("PALETTE.%s matches --%s in globals.css", (ogKey, cssToken) => {
    expect(ogColour(ogKey)).toBe(token(cssToken));
  });
});

describe("lime is the only saturated thing at rest on the page", () => {
  // RULE CHANGED with the graphite theme. Amber required every grey to sit in
  // the warm hue band (20–110°) with chroma under 0.04, because a cool grey
  // read as a second accent next to amber. Graphite is deliberately neutral,
  // so the HUE band is dropped — at chroma ≤ 0.015 hue is imperceptible, and
  // #f2f3f0 sits at 122° while the surfaces sit near 265° — and the CHROMA
  // bar is TIGHTENED from 0.04 to 0.02, which is the part that actually stops
  // a grey from competing with the accent.
  //
  // --loss left this list: it is now a red money channel, asserted separately
  // under "win and loss" and "no semantic channel collapses into the accent".
  it.each([
    "bg",
    "surface",
    "surface-raised",
    "surface-sunken",
    "border",
    "border-lit",
    "border-input",
    "text",
    "text-dim",
    "muted",
    "faint",
    "neg",
    "neutral",
    "series-grid",
  ])("--%s is a neutral grey with no real chroma", (name) => {
    expect(oklch(token(name)).c).toBeLessThan(0.02);
  });

  it("the accent is unmistakably chromatic by comparison", () => {
    expect(oklch(token("signal-500")).c).toBeGreaterThan(0.15);
  });

  it("the consensus series is the ONE deliberate cool exception", () => {
    // It has to be cool: that is what makes it separable from amber for a
    // red-green-deficient reader. Pinned here so the exception stays a
    // decision rather than an oversight.
    const { h } = oklch(token("series-consensus"));
    expect(h).toBeGreaterThan(180);
    expect(h).toBeLessThan(300);
  });
});

describe("dashboard rows", () => {
  it("row text clears 4.5:1 on the row surface", () => {
    for (const name of ["text", "muted", "faint", "row-muted"]) {
      expect(contrast(token(name), token("row-surface")), `--${name}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("an open row's border clears 3:1 against the page", () => {
    expect(contrast(token("row-open-border"), BG())).toBeGreaterThanOrEqual(3);
  });
});
