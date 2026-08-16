"use client";

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
    <div className="relative flex-1 sm:max-w-[280px]">
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search teams…"
        aria-label="Search by team name"
        className="w-full rounded-md border border-border bg-surface px-3 py-1.5 text-body text-text placeholder:text-faint focus:border-border-lit"
      />
      {value ? (
        <span className="tabular pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-micro text-faint">
          {resultCount}
        </span>
      ) : null}
    </div>
  );
}
