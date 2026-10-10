import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A falsifiable monitor for the type system, in the same spirit as
 * palette.test.ts: it reads the files that actually ship, not a copy.
 *
 * What is enforced, and why:
 *
 *  1. Two faces only — Inter for everything, Unbounded (400 and 500) for the
 *     display numbers and the wordmark — both bundled by next/font. The app
 *     used to be JetBrains Mono throughout; nothing of that may come back, and
 *     no stylesheet may be fetched from Google at runtime.
 *  2. Sentence case. The amber theme set section titles, tile labels and the
 *     status pill in uppercase, letter-spaced mono. That style is gone, and so
 *     is the `.label` class that applied it.
 *  3. A size floor. Nothing under 12px, anywhere. The old scale went down to
 *     10px, which read as noise at the top of the page.
 *  4. No amber left in the stylesheet.
 *
 * The browser audit checks the same floor on COMPUTED sizes; this catches it
 * at the source, before anything renders.
 */

const ROOT = process.cwd();
const SRC = join(ROOT, "src");
const CSS = readFileSync(join(SRC, "app/globals.css"), "utf8");
const LAYOUT = readFileSync(join(SRC, "app/layout.tsx"), "utf8");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

/** Shipping source: components, pages and libs — not tests or generated data. */
const SOURCES = walk(SRC)
  .filter((f) => /\.(tsx?|css)$/.test(f))
  .filter((f) => !/\.test\.ts$/.test(f) && !f.endsWith("teams.generated.ts"))
  .map((f) => ({ file: relative(ROOT, f), text: readFileSync(f, "utf8") }));

const TSX = SOURCES.filter((s) => s.file.endsWith(".tsx"));

/** Strip comments, so prose that EXPLAINS a retired rule is not a violation. */
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function hits(re: RegExp, files = SOURCES): string[] {
  return files.flatMap(({ file, text }) =>
    [...code(text).matchAll(re)].map((m) => `${file}: ${m[0]}`),
  );
}

describe("two faces, both bundled", () => {
  it("loads exactly Inter and Unbounded from next/font", () => {
    const m = LAYOUT.match(/import\s*\{([^}]*)\}\s*from\s*"next\/font\/google"/);
    expect(m, "layout.tsx must load its fonts through next/font/google").not.toBeNull();
    const names = m![1].split(",").map((s) => s.trim()).filter(Boolean).sort();
    expect(names).toEqual(["Inter", "Unbounded"]);
  });

  it("loads Unbounded in weights 400 and 500 only", () => {
    const block = LAYOUT.match(/Unbounded\(\{([\s\S]*?)\}\)/);
    expect(block).not.toBeNull();
    const weights = block![1].match(/weight:\s*\[([^\]]*)\]/);
    expect(weights, "Unbounded must pin its weights explicitly").not.toBeNull();
    expect(weights![1].replace(/[\s"']/g, "").split(",").sort()).toEqual(["400", "500"]);
  });

  it("never fetches a stylesheet or font from Google at runtime", () => {
    expect(hits(/fonts\.(googleapis|gstatic)\.com/g)).toEqual([]);
  });

  it("has no mono face anywhere", () => {
    expect(hits(/JetBrains|monospace|ui-monospace|font-mono|--stack-mono|--font-data/gi)).toEqual(
      [],
    );
  });

  it("sets the body in Inter", () => {
    expect(CSS).toMatch(/body\s*\{[^}]*font-family:\s*var\(--stack-sans\)/);
    expect(CSS).toMatch(/--stack-sans:\s*var\(--font-inter/);
    expect(CSS).toMatch(/--stack-display:\s*var\(--font-unbounded/);
  });

  it("never asks Unbounded for a weight that is not bundled", () => {
    // A bold utility on a `.display` element would be synthesised by the
    // browser rather than drawn by the font.
    const bad = TSX.flatMap(({ file, text }) =>
      [...text.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)]
        .map((m) => m[1] ?? m[2])
        .filter((c) => /(^|\s)display(-medium)?(\s|$)/.test(c))
        .filter((c) => /font-(semibold|bold|extrabold|black|light|thin)/.test(c))
        .map((c) => `${file}: ${c}`),
    );
    expect(bad).toEqual([]);
  });
});

describe("sentence case", () => {
  it("has no uppercase or letter-spaced label style", () => {
    expect(hits(/\buppercase\b|tracking-(wide|wider|widest)|text-transform:\s*uppercase/g)).toEqual(
      [],
    );
  });

  it("no longer defines or uses the .label class", () => {
    expect(CSS).not.toMatch(/^\.label\s*\{/m);
    const uses = TSX.flatMap(({ file, text }) =>
      [...text.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)]
        .map((m) => m[1] ?? m[2])
        .filter((c) => /(^|\s)label(\s|$)/.test(c))
        .map((c) => `${file}: ${c}`),
    );
    expect(uses).toEqual([]);
  });
});

describe("nothing under 12px", () => {
  it("every type-scale token is at least 12px", () => {
    const sizes = [...CSS.matchAll(/--text-([a-z]+):\s*([0-9.]+)px\s*;/g)];
    expect(sizes.length).toBeGreaterThanOrEqual(7);
    for (const [, name, px] of sizes) {
      expect(Number(px), `--text-${name}`).toBeGreaterThanOrEqual(12);
    }
  });

  it("secondary text is 13px and body text 14px", () => {
    expect(CSS).toMatch(/--text-meta:\s*13px/);
    expect(CSS).toMatch(/--text-body:\s*14px/);
  });

  it("no arbitrary text-[Npx] utility is under 12px", () => {
    const small = hits(/text-\[([0-9.]+)px\]/g, TSX).filter((h) => {
      const px = Number(h.match(/text-\[([0-9.]+)px\]/)![1]);
      return px < 12;
    });
    expect(small).toEqual([]);
  });

  it("no rem/em arbitrary size, which would dodge the px check", () => {
    expect(hits(/text-\[[0-9.]+r?em\]/g, TSX)).toEqual([]);
  });

  it("no Tailwind size utility under 12px is used", () => {
    // text-xs is exactly 12px and allowed; there is no smaller default step,
    // but a 2xs/3xs plugin step would be caught here.
    expect(hits(/\btext-[23]xs\b/g, TSX)).toEqual([]);
  });

  it("no inline fontSize (charts, share image) is under 12px", () => {
    const small = hits(/fontSize:\s*([0-9.]+)/g, TSX).filter(
      (h) => Number(h.match(/fontSize:\s*([0-9.]+)/)![1]) < 12,
    );
    expect(small).toEqual([]);
  });

  it("no CSS font-size is under 12px", () => {
    const small = [...CSS.matchAll(/font-size:\s*([0-9.]+)px/g)].filter((m) => Number(m[1]) < 12);
    expect(small.map((m) => m[0])).toEqual([]);
  });
});

describe("no amber left", () => {
  // The amber theme's own values, from git history. If any reappears in the
  // stylesheet or a component, a piece of the old theme came back with it.
  const AMBER = [
    "#0b0a09",
    "#141210",
    "#f2ede4",
    "#f2c14e",
    "#d9a93f",
    "#7d6222",
    "#211a0a",
    "#ffa62e",
    "#edb945",
    "#cf6f4a",
    "#3fae9e",
    "#8fa3b8",
  ];
  it.each(AMBER)("%s does not appear in shipping source", (hex) => {
    expect(hits(new RegExp(hex, "gi"))).toEqual([]);
  });
});
