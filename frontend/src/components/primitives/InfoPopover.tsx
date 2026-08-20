"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";
import { useIsClient } from "@/lib/useIsClient";

/** Space between the trigger and the visible panel. Bridged — see below. */
const GAP = 6;
/** Keep the viewport edge clear by this much. */
const MARGIN = 8;
/**
 * Grace period before a hover-out actually closes. Belt-and-braces alongside
 * the bridge: a diagonal exit can leave both boxes for a frame.
 */
const CLOSE_GRACE_MS = 120;

/**
 * A "?" next to a jargon term, revealing a plain-English line in place.
 *
 * ---------------------------------------------------------------------------
 * WHY THIS RENDERS THROUGH A PORTAL
 *
 * The panel contains a link to the full explanation. Rendered inline, that link
 * became an <a> inside whatever <a> the trigger happened to sit in — the
 * "Interesting right now" tiles are whole-card links — which is invalid HTML
 * and made React log "In HTML, <a> cannot be a descendant of <a>. This will
 * cause a hydration error."
 *
 * The fix is at the COMPONENT level rather than at the one call site that
 * tripped it. This is a shared primitive dropped into dense cards all over the
 * app; fixing InterestingNow alone would leave the same trap armed for the next
 * linked card. Portalling to <body> makes invalid nesting structurally
 * impossible wherever it is used.
 *
 * It also fixes a quieter bug: inline, the panel was INSIDE the card's link, so
 * clicking anything in it — including "More on this" — also activated the card
 * link underneath. Outside the anchor, that cannot happen.
 *
 * ---------------------------------------------------------------------------
 * WHY THE PANEL IS BRIDGED TO THE TRIGGER
 *
 * Separately from the nesting, the panel could not be reached with a mouse at
 * all: it sits GAP px above the "?", and that gap belonged to neither element,
 * so moving toward the panel fired pointerleave and closed it. Measured on a
 * popover with no link ancestor as well, which is how we know the outer link
 * was never the cause.
 *
 * So the portalled element spans the gap — the visible card is drawn inside a
 * wrapper whose padding covers the dead space down to the trigger's edge —
 * and pointer handlers are attached to the panel as well as the trigger, since
 * a portal's events do not bubble to the trigger's DOM position.
 * ---------------------------------------------------------------------------
 *
 * Touch is a first-class input: hover is gated on `pointerType === "mouse"`
 * because touch browsers synthesise mouse events, tap toggles, and an outside
 * `pointerdown` closes. `.tap` gives the 14px button a 44px hit area.
 */
type Placement = "above" | "below";

interface Position {
  left: number;
  top: number;
  width: number;
  placement: Placement;
}

export function InfoPopover({ term }: { term: GlossaryKey }) {
  const entry = GLOSSARY[term];
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<Position | null>(null);
  const id = useId();
  const isClient = useIsClient();

  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const moreLink = useRef<HTMLAnchorElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelClose = useCallback(() => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  const scheduleClose = useCallback(() => {
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), CLOSE_GRACE_MS);
  }, [cancelClose]);

  useEffect(() => cancelClose, [cancelClose]);

  /**
   * Place the panel against the trigger's viewport rect.
   *
   * Measured rather than guessed at a breakpoint: the trigger's position
   * depends on the row it sits in, not on the screen width. Runs in a layout
   * effect so the panel is never painted at a provisional position.
   */
  const place = useCallback(() => {
    const t = trigger.current;
    const c = card.current;
    if (!t || !c) return;

    const tr = t.getBoundingClientRect();
    const width = Math.min(260, window.innerWidth - MARGIN * 2);
    const height = c.offsetHeight;

    // Above by default; flip below only when there is genuinely no room, so a
    // popover near the top of the list does not get clipped.
    const placement: Placement = tr.top - GAP - height < MARGIN ? "below" : "above";

    let left = tr.left + tr.width / 2 - width / 2;
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - width - MARGIN));

    const top = placement === "above" ? tr.top - GAP - height : tr.bottom;
    setPos({ left, top, width, placement });
  }, []);

  // No reset on close: the panel unmounts, and a layout effect runs before
  // paint, so a stale position from the previous open can never be shown.
  useLayoutEffect(() => {
    if (!open) return;
    place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    const onDown = (e: Event) => {
      const target = e.target as Node;
      if (trigger.current?.contains(target)) return;
      if (panel.current?.contains(target)) return;
      setOpen(false);
    };
    // The panel is fixed-positioned against a viewport rect, so it has to be
    // re-placed rather than left behind when the page moves under it.
    const reflow = () => place();

    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("scroll", reflow, true);
    window.addEventListener("resize", reflow);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("scroll", reflow, true);
      window.removeEventListener("resize", reflow);
    };
  }, [open, place]);

  const hoverOnly = useCallback(
    (next: boolean) => (e: React.PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      if (next) {
        cancelClose();
        setOpen(true);
      } else {
        scheduleClose();
      }
    },
    [cancelClose, scheduleClose],
  );

  const panelNode =
    open && isClient
      ? createPortal(
          <div
            ref={panel}
            // The wrapper spans the GAP down to the trigger so the dead space
            // between them is still "inside" the popover. Without this the
            // panel is unreachable with a mouse.
            style={{
              position: "fixed",
              left: pos?.left ?? 0,
              top: pos?.top ?? 0,
              width: pos?.width ?? 260,
              paddingBottom: pos?.placement === "above" ? GAP : 0,
              paddingTop: pos?.placement === "below" ? GAP : 0,
              // Hidden only for the single frame before it has been measured.
              visibility: pos ? "visible" : "hidden",
              zIndex: 50,
            }}
            onPointerEnter={hoverOnly(true)}
            onPointerLeave={hoverOnly(false)}
          >
            <div
              ref={card}
              id={id}
              role="tooltip"
              className="rounded-md border border-border-lit bg-surface p-2.5 text-left shadow-[var(--shadow-panel)]"
            >
              <span className="label block text-micro font-semibold text-dim">{entry.term}</span>
              <span className="mt-1 block text-meta leading-[1.5] text-muted">{entry.short}</span>
              <Link
                ref={moreLink}
                href={`/how-it-works#${entry.anchor}`}
                onClick={() => setOpen(false)}
                onKeyDown={(e) => {
                  // Tab order follows the DOM, and the DOM says this link is at
                  // the end of <body>. Hand focus back to the trigger so a
                  // keyboard user does not get dumped out of the page.
                  if (e.key === "Tab" && e.shiftKey) {
                    e.preventDefault();
                    setOpen(false);
                    trigger.current?.focus();
                  }
                }}
                className="tap mt-1.5 inline-block text-meta text-signal-600 hover:text-signal"
              >
                More on this →
              </Link>
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <span
      className="relative z-20 inline-flex"
      onPointerEnter={hoverOnly(true)}
      onPointerLeave={hoverOnly(false)}
    >
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={`What does ${entry.term} mean?`}
        onClick={(e) => {
          // The trigger may sit inside a linked card; never navigate it.
          e.preventDefault();
          e.stopPropagation();
          cancelClose();
          setOpen((v) => !v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Tab" && !e.shiftKey && open) {
            e.preventDefault();
            moreLink.current?.focus();
          }
        }}
        className={`tap flex h-[14px] w-[14px] items-center justify-center rounded-sm border text-[9px] leading-none transition-colors ${
          open
            ? "border-signal text-signal"
            : "border-border-lit text-muted hover:border-signal hover:text-signal"
        }`}
      >
        ?
      </button>
      {panelNode}
    </span>
  );
}
