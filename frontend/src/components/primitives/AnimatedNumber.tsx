"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Counts from the previous value to the new one instead of snapping.
 *
 * The animation is cosmetic but the numbers are not, so two rules hold: it
 * always LANDS exactly on the target (no easing residue leaving 99.98 where the
 * data says 100), and it is skipped entirely under prefers-reduced-motion,
 * where the value updates instantly rather than not at all.
 *
 * There is no animation on first paint — a price ticking up from zero on load
 * would imply a move that never happened.
 */
const DURATION = 420;

export function useAnimatedNumber(target: number, duration = DURATION): number {
  const [value, setValue] = useState(target);
  const from = useRef(target);
  const frame = useRef<number | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      from.current = target;
      setValue(target);
      return;
    }

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduced || from.current === target) {
      from.current = target;
      setValue(target);
      return;
    }

    const start = performance.now();
    const origin = from.current;
    const delta = target - origin;

    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // easeOutCubic
      const eased = 1 - (1 - t) ** 3;
      if (t >= 1) {
        from.current = target;
        setValue(target); // land exactly on the real value
        return;
      }
      setValue(origin + delta * eased);
      frame.current = requestAnimationFrame(step);
    };

    frame.current = requestAnimationFrame(step);
    return () => {
      if (frame.current != null) cancelAnimationFrame(frame.current);
      from.current = target;
    };
  }, [target, duration]);

  return value;
}

export function AnimatedNumber({
  value,
  format,
  className = "",
}: {
  value: number;
  format: (n: number) => string;
  className?: string;
}) {
  const animated = useAnimatedNumber(value);
  return (
    <span className={className} suppressHydrationWarning>
      {format(animated)}
    </span>
  );
}
