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
 *  5. Every grey stays WARM. Amber is meant to be the only warm thing on the
 *     page; a cool grey creeping in reads as a second accent.
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
const SUNKEN = () => token("surface-sunken");

describe("text contrast", () => {
  it.each([
    ["text", 7],
    ["text-dim", 4.5],
    ["muted", 4.5],
  ])("--%s clears %s:1 on both --bg and --surface", (name, min) => {
    expect(contrast(token(name), BG())).toBeGreaterThanOrEqual(min);
    expect(contrast(token(name), SURFACE())).toBeGreaterThanOrEqual(min);
  });

  it("--faint is legible enough for provenance, and is the only step below 4.5", () => {
    // Documented as timestamps/footnotes only. Asserted so nobody promotes it
    // to body copy without this failing.
    const c = contrast(token("faint"), SURFACE());
    expect(c).toBeGreaterThanOrEqual(2);
    expect(c).toBeLessThan(4.5);
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
    ["status-ok", 4.5],
    ["gain", 4.5],
    ["loss", 4.5],
    ["signal-800", 3], // strokes and borders only
  ])("--%s clears %s:1 on --surface", (name, min) => {
    expect(contrast(token(name), SURFACE())).toBeGreaterThanOrEqual(min);
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

  it.each(["neg", "loss", "warn", "status-ok"])(
    "--%s is clearly distinct from --signal-500",
    (name) => {
      expect(deltaE(token(name), SIGNAL())).toBeGreaterThanOrEqual(15);
      expect(
        deltaE(simulate(token(name), "protan"), simulate(SIGNAL(), "protan")),
      ).toBeGreaterThanOrEqual(12);
    },
  );

  it("--gain DOES share the amber family, deliberately", () => {
    // The rule is that value is amber and its absence is not. A gain that
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

describe("amber is the only warm thing on the page", () => {
  it.each([
    "surface",
    "surface-raised",
    "surface-sunken",
    "border",
    "border-lit",
    "text",
    "text-dim",
    "muted",
    "faint",
    "loss",
    "neg",
    "neutral",
    "series-grid",
  ])("--%s is a warm neutral, not a cool one", (name) => {
    const { h, c } = oklch(token(name));
    // Warm half of the wheel (orange through yellow-green).
    expect(h).toBeGreaterThanOrEqual(20);
    expect(h).toBeLessThanOrEqual(110);
    // ...and desaturated, so it cannot read as a second accent.
    expect(c).toBeLessThan(0.04);
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
