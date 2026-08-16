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

export function kickoff(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return DASH;
  return (
    dt.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " · " +
    dt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  );
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
