"use client";

/**
 * Team search.
 *
 * `text-body` is 13px, and iOS Safari zooms the whole viewport when a focused
 * input is under 16px — which on a phone left the sticky toolbar scrolled
 * half off-screen with no obvious way back. globals.css raises every input to
 * 16px below the `sm` breakpoint; the class here stays 13px so the desktop
 * density is unchanged.
 *
 * `enterKeyHint="search"` labels the on-screen keyboard's action key, and the
 * type is `search` so mobile browsers offer their own clear affordance.
 */
export function SearchBar({
  value,
  onChange,
  resultCount,
}: {
  value: string;
  onChange: (v: string) => void;
  resultCount: number;
}) {
  return (
    <div className="relative min-w-0 flex-1 sm:max-w-[280px]">
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search teams…"
        aria-label="Search by team name"
        enterKeyHint="search"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        className="data w-full rounded-sm border border-border bg-surface px-2.5 py-1.5 text-body text-text placeholder:text-faint focus:border-border-lit sm:px-3"
      />
      {value ? (
        <span className="tabular pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-micro text-faint">
          {resultCount}
        </span>
      ) : null}
    </div>
  );
}
