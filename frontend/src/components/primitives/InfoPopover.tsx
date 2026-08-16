"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

/**
 * A "?" next to a jargon term, revealing a plain-English line in place.
 *
 * Opens on hover AND on click: hover serves a mouse, click serves touch and
 * keyboard, and neither is sufficient alone. It is a real <button> with
 * aria-expanded rather than a styled span, and it links through to the fuller
 * explanation so the popover is a doorway rather than a dead end.
 */
export function InfoPopover({ term }: { term: GlossaryKey }) {
  const entry = GLOSSARY[term];
  const [open, setOpen] = useState(false);
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onClick = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <span
      ref={wrap}
      className="relative z-20 inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
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
        className="flex h-[13px] w-[13px] items-center justify-center rounded-full border border-border-lit text-[9px] leading-none text-muted transition-colors hover:border-signal hover:text-signal"
      >
        ?
      </button>

      {open ? (
        <span
          id={id}
          role="tooltip"
          className="absolute bottom-full left-1/2 z-50 mb-1.5 w-[260px] -translate-x-1/2 rounded-md border border-border-lit bg-surface p-2.5 text-left shadow-[var(--shadow-panel)]"
        >
          <span className="block text-micro font-semibold uppercase tracking-[0.06em] text-dim">
            {entry.term}
          </span>
          <span className="mt-1 block text-meta leading-[1.5] text-muted">{entry.short}</span>
          <Link
            href={`/how-it-works#${entry.anchor}`}
            onClick={(e) => e.stopPropagation()}
            className="mt-1.5 inline-block text-meta text-signal-600 hover:text-signal"
          >
            More on this →
          </Link>
        </span>
      ) : null}
    </span>
  );
}
