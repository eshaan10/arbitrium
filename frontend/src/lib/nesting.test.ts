import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A structural guard against interactive elements nesting inside a link.
 *
 * HTML forbids an <a> inside an <a>, and forbids interactive content inside an
 * <a> at all. Both were happening: the "Interesting right now" tiles wrapped
 * their whole body in a <Link>, and that body contains an InfoPopover — a
 * <button> whose panel contains another <a>. React logged "In HTML, <a> cannot
 * be a descendant of <a>. This will cause a hydration error."
 *
 * These assertions are deliberately about STRUCTURE rather than rendering,
 * because the rendering test that actually proves it needs a browser: a jsdom
 * assertion would not exercise the portal, the hover path, or the click. The
 * browser check lives in the verification pass; this is the cheap tripwire that
 * fails in CI if someone reverts the mechanism that makes it safe.
 */

const read = (rel: string) => readFileSync(join(process.cwd(), "src", rel), "utf8");

describe("InfoPopover cannot nest inside a link", () => {
  const src = read("components/primitives/InfoPopover.tsx");

  it("renders its panel through a portal", () => {
    // The portal is the whole mechanism: it moves the panel — and the <a> it
    // contains — out of whatever ancestor the trigger happens to sit in. Fixing
    // only the one call site that tripped this would leave the trap armed for
    // the next linked card.
    expect(src).toMatch(/import\s*\{[^}]*createPortal[^}]*\}\s*from\s*"react-dom"/);
    expect(src).toMatch(/createPortal\(/);
    expect(src).toMatch(/document\.body/);
  });

  it("bridges the gap between trigger and panel", () => {
    // Separately from the nesting: the panel sits GAP px above the trigger, and
    // that dead space belonged to neither element, so moving toward the panel
    // fired pointerleave and closed it before it could be clicked. The portal
    // alone would make this worse, not better — the panel stops being a DOM
    // descendant, so it needs its own pointer handlers plus a bridge.
    expect(src).toMatch(/paddingBottom/);
    expect(src).toMatch(/onPointerEnter/);
    expect(src).toMatch(/CLOSE_GRACE_MS/);
  });

  it("keeps the panel's own hover handlers, or a mouse can never reach it", () => {
    // Two handlers minimum: one pair on the trigger, one pair on the portalled
    // panel. A portal's events do not bubble to the trigger's DOM position.
    const enters = src.match(/onPointerEnter/g) ?? [];
    const leaves = src.match(/onPointerLeave/g) ?? [];
    expect(enters.length).toBeGreaterThanOrEqual(2);
    expect(leaves.length).toBeGreaterThanOrEqual(2);
  });
});

describe("cards that contain controls use an overlay link", () => {
  it.each([
    ["components/dashboard/InterestingNow.tsx", "InterestingNow tile"],
    ["components/event/EventCard.tsx", "EventCard"],
  ])("%s does not wrap its body in a <Link>", (rel) => {
    const src = read(rel);
    // The safe pattern: a positioned container with an absolutely positioned
    // overlay <Link>, and controls stacked above it. Both files contain an
    // InfoPopover or a button, so neither may wrap its content in an anchor.
    expect(src).toMatch(/className="absolute inset-0 z-10/);
    // A self-closing overlay link has no children by construction.
    expect(src).not.toMatch(/<Link[^>]*>\s*\{body\}/);
  });
});
