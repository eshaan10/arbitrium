"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

const MARGIN = 8;

/**
 * A "?" next to a jargon term, revealing a plain-English line in place.
 *
 * TOUCH is a first-class input here, not an afterthought:
 *
 *  - Hover opens it only for a MOUSE. `pointerType` is checked rather than
 *    trusting `onMouseEnter`, because touch browsers synthesise mouse events —
 *    which made the first tap "hover open" and the second tap "click closed",
 *    so on a phone the panel appeared to need two taps and then flicker away.
 *  - Tap toggles, and a tap anywhere outside closes. The outside listener is on
 *    `pointerdown`, which fires for both input kinds; `mousedown` alone did not
 *    reliably fire on iOS, leaving popovers stuck open.
 *  - The `.tap` class gives the 13px button a 44px hit area on coarse pointers
 *    without changing how it looks.
 *
 * It is a real <button> with aria-expanded rather than a styled span, and it
 * links through to the fuller explanation so the popover is a doorway rather
 * than a dead end.
 */
export function InfoPopover({ term }: { term: GlossaryKey }) {
  const entry = GLOSSARY[term];
  const [open, setOpen] = useState(false);
  const [shift, setShift] = useState(0);
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  const panel = useRef<HTMLSpanElement>(null);

  /**
   * Keep the panel inside the viewport. It is centred on the trigger, which on
   * a phone puts half of it off-screen for anything near an edge — and a
   * clipped explanation is worse than none, because the reader cannot tell
   * there is more. Measured rather than guessed at a breakpoint: the trigger's
   * position depends on the row it sits in, not on the screen width.
   */
  useLayoutEffect(() => {
    if (!open || !panel.current) return;
    setShift(0);
    const r = panel.current.getBoundingClientRect();
    const overflowRight = r.right - (window.innerWidth - MARGIN);
    const overflowLeft = MARGIN - r.left;
    if (overflowRight > 0) setShift(-overflowRight);
    else if (overflowLeft > 0) setShift(overflowLeft);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onDown = (e: Event) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  const hoverOnly = useCallback(
    (next: boolean) => (e: React.PointerEvent) => {
      if (e.pointerType === "mouse") setOpen(next);
    },
    [],
  );

  return (
    <span
      ref={wrap}
      className="relative z-20 inline-flex"
      onPointerEnter={hoverOnly(true)}
      onPointerLeave={hoverOnly(false)}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`What does ${entry.term} mean?`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className={`tap flex h-[14px] w-[14px] items-center justify-center rounded-sm border text-[9px] leading-none transition-colors ${
          open ? "border-signal text-signal" : "border-border-lit text-muted hover:border-signal hover:text-signal"
        }`}
      >
        ?
      </button>

      {open ? (
        <span
          id={id}
          ref={panel}
          role="tooltip"
          style={{ transform: `translateX(calc(-50% + ${shift}px))` }}
          className="absolute bottom-full left-1/2 z-50 mb-1.5 w-[min(260px,calc(100vw-2rem))] rounded-md border border-border-lit bg-surface p-2.5 text-left shadow-[var(--shadow-panel)]"
        >
          <span className="label block text-micro font-semibold text-dim">{entry.term}</span>
          <span className="mt-1 block text-meta leading-[1.5] text-muted">{entry.short}</span>
          <Link
            href={`/how-it-works#${entry.anchor}`}
            onClick={(e) => e.stopPropagation()}
            className="tap mt-1.5 inline-block text-meta text-signal-600 hover:text-signal"
          >
            More on this →
          </Link>
        </span>
      ) : null}
    </span>
  );
}
