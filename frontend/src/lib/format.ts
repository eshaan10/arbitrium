const DASH = "—";

export function pct(x: number | null | undefined, places = 2): string {
  return x == null || Number.isNaN(x) ? DASH : `${(x * 100).toFixed(places)}%`;
}

export function money(x: number | null | undefined): string {
  return x == null || Number.isNaN(x) ? DASH : `$${x.toFixed(2)}`;
}

/** Kalshi prices are quoted in cents, so the UI quotes them in cents too. */
export function cents(x: number | null | undefined): string {
  return x == null || Number.isNaN(x) ? DASH : `${Math.round(x * 100)}¢`;
}

export function num(n: number | null | undefined): string {
  return n == null || Number.isNaN(n) ? DASH : Math.round(n).toLocaleString();
}

export function americanStr(v: number): string {
  return `${v > 0 ? "+" : ""}${Math.round(v)}`;
}

export function impliedFromAmerican(v: number): number {
  return v > 0 ? 100 / (v + 100) : -v / (-v + 100);
}

/**
 * The zone a kickoff is rendered in when the viewer's own zone isn't knowable.
 *
 * The server has no way to learn the browser's timezone, and rendering in the
 * server's zone silently showed a Pacific reader a game at 8:25 PM that starts
 * at 1:25 PM for them — and produced a hydration mismatch on the way. So the
 * server and the hydration pass both format in one FIXED zone, which makes the
 * two renders identical by construction; `KickoffTime` swaps to the viewer's
 * own zone after mount. US sports schedules are quoted in Eastern, so that is
 * the least surprising thing to show in the meantime.
 */
export const REFERENCE_TIME_ZONE = "America/New_York";
export const REFERENCE_LOCALE = "en-US";

/**
 * "Sep 13 · 8:25 PM EDT".
 *
 * Always carries a zone label. The pre-mount and post-mount renders show
 * different clock times by design, and an unlabelled time would leave a reader
 * unable to tell which one they are looking at.
 *
 * Pass no options for the viewer's own locale and zone (browser only). Pass
 * both for a deterministic string — required anywhere the server renders it.
 */
export function kickoff(
  iso: string | null | undefined,
  opts?: { locale?: string; timeZone?: string; separator?: string },
): string {
  if (!iso) return DASH;
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return DASH;
  const locale = opts?.locale;
  const timeZone = opts?.timeZone;
  return (
    dt.toLocaleDateString(locale, {
      month: "short",
      day: "numeric",
      timeZone,
    }) +
    (opts?.separator ?? " · ") +
    dt.toLocaleTimeString(locale, {
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
      timeZone,
    })
  );
}

/** The fixed-zone form. Safe to render on the server; never depends on a clock. */
export function kickoffFixed(iso: string | null | undefined, separator?: string): string {
  return kickoff(iso, {
    locale: REFERENCE_LOCALE,
    timeZone: REFERENCE_TIME_ZONE,
    separator,
  });
}

/** "in 4 days" / "in 5 hours" / "in 12 minutes" / "started" — the spelled-out form. */
export function timeToKickoffLong(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - now;
  if (Number.isNaN(ms)) return "";
  if (ms <= 0) return "started";
  const unit = (n: number, word: string) => `in ${n} ${word}${n === 1 ? "" : "s"}`;
  const minutes = Math.max(1, Math.round(ms / 60_000));
  if (minutes < 60) return unit(minutes, "minute");
  const hours = Math.round(ms / 3_600_000);
  if (hours < 48) return unit(hours, "hour");
  return unit(Math.round(hours / 24), "day");
}

/** "in 3 days" / "in 2h" / "started" — relative to now, coarse on purpose. */
export function timeToKickoff(iso: string | null | undefined): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "";
  if (ms <= 0) return "started";
  const hours = ms / 3_600_000;
  if (hours < 1) return `in ${Math.round(ms / 60_000)}m`;
  if (hours < 48) return `in ${Math.round(hours)}h`;
  return `in ${Math.round(hours / 24)}d`;
}

export function plural(n: number | null | undefined, one: string, many: string): string {
  return n === 1 ? one : many;
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * The sportsbooks' fair value, in cents, beside a Kalshi price.
 *
 * Whole cents normally. When the two would round to the SAME cent, one decimal
 * is shown instead: "Buy Yes · 21¢ — sportsbooks say 21¢" reads as no edge at
 * all, when the real figures are 21¢ against 21.4¢.
 */
/**
 * The gap between the sportsbooks' fair value and the Kalshi price, signed:
 * "+2¢". Same rounding rule as `fairValueCents`, so the chip agrees with the
 * two prices printed beside it — a gap that rounds to nothing shows one
 * decimal rather than a misleading "+0¢".
 */
export function edgeCents(fair: number | null | undefined, price: number | null | undefined): string {
  if (fair == null || price == null || Number.isNaN(fair) || Number.isNaN(price)) return DASH;
  const diff = (fair - price) * 100;
  const sign = diff < 0 ? "−" : "+";
  const whole = Math.round(Math.abs(diff));
  return whole === 0 ? `${sign}${Math.abs(diff).toFixed(1)}¢` : `${sign}${whole}¢`;
}

export function fairValueCents(fair: number | null | undefined, price: number | null | undefined): string {
  if (fair == null || Number.isNaN(fair)) return DASH;
  if (price != null && Math.round(fair * 100) === Math.round(price * 100)) {
    return `${(fair * 100).toFixed(1)}¢`;
  }
  return cents(fair);
}
