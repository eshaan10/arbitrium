# Arbitrium frontend

Next.js 16 (App Router) UI for the divergence engine. Dark, Kalshi-native, and
built so that no screen can quietly become more confident than the data behind
it.

## Running

```bash
pnpm install
cp .env.example .env.local        # BACKEND_URL, server-side only
pnpm dev                          # http://localhost:3000
```

Or with the whole stack: `docker compose up frontend` from the repo root, which
points `BACKEND_URL` at the `api` service.

## How it talks to the backend

The browser never calls FastAPI directly. Server components fetch it over
`BACKEND_URL`; the client polls through the Next route handler at
`/api/be/[...path]`, which forwards a small allowlist of GET endpoints. So the
backend origin stays server-side and FastAPI needs no CORS policy for this app.

`src/lib/types.ts` is a hand-written mirror of the API response bodies. It is
**not** generated: every endpoint in `backend/arbitrium/api/main.py` is
annotated `-> dict`, so the published OpenAPI schema carries no response shape
and codegen would emit `unknown`. If the API changes, that file changes with it.

## Layout

```
src/app/                 routes: dashboard, events/[id], combos, performance
src/components/
  primitives/            Card, Badge, ConfidenceBars, Metric, EmptyState
  recommendation/        the Simple-mode content: headline, why, stake simulator
  advanced/              the Advanced-mode content: metrics, books, arbitrage
  event/                 cards, status explainers, outcome sections, charts
  dashboard/  combos/  performance/
src/lib/                 api client, types, formatting, confidence, copy
```

Simple vs Advanced is **structural**, not a CSS toggle: Advanced mounts extra
components. Jargon stays out of Simple mode because it is not rendered there,
not because a class is hiding it. The mode lives in the URL (`?mode=advanced`),
as do the sport tab, list filter, and combo risk tier, so any view is shareable
and server-rendered correctly on first paint.

## Rules the UI is built to keep

- **Lead with the recommendation.** "Buy Yes <team> at 40¢", in plain English,
  with every number in the sentence taken from the event. Technical metrics
  never occupy the headline slot.
- **Never a single blended number for a directional bet.** The stake simulator
  always shows both outcomes. One guaranteed figure exists in this product and
  it belongs to true arbitrage, which is fenced into its own panel.
- **Arbitrage is secondary.** A muted tag on the card, the full panel only in
  the detail view, and an explicit note when a leg is not on Kalshi at all.
- **Unscoreable events are shown, with the reason.** Filtering them out would
  let a reader assume the game does not exist.
- **The confidence fade has a floor** (`--fade-floor`, 0.62) so the dimmest row
  still clears 4.5:1. Opacity reinforces the explicit confidence label; it is
  never the only carrier.
- **The sample gate belongs to the API.** `/performance` decides when a rate may
  be reported; this UI renders that verdict and never computes its own.

## Team logos and colours

`src/lib/teams.generated.ts` and `public/logos/nfl/` are produced by
`pnpm gen:teams`. Logos are **vendored, not hotlinked** — they appear on every
card and should not depend on a third-party CDN at runtime.

Two things that script exists to get right:

- **Codes come from ESPN's own team list, never from the backend's
  `reference/teams.py`.** The two disagree: that file has `WAS`, ESPN serves
  `wsh` and 404s on `was`.
- **Brand colours are lifted, not used raw.** 22 of 32 primaries fall under 3:1
  against `--bg`. Each is raised in OKLCH until it clears 3.2:1 with its hue
  intact, and `pnpm test` asserts every committed value still does — so an
  upstream colour change fails a test instead of silently shipping an
  unreadable accent.

Dallas, New England and Seattle share one brand colour upstream, as do the
Raiders and Steelers, so `matchupVisuals()` drops the away team to its alternate
when both sides of a card would otherwise draw the same bar.

## Personalisation

Everything is localStorage; there are no accounts and nothing leaves the
browser. Values that fail to parse degrade to empty rather than throwing, and
state is read through `useSyncExternalStore`, so the server snapshot is the
default, the first client render matches it, and changes propagate across tabs.

Two **independent** lists, deliberately not one:

| Verb | Key | Holds | Affordance |
|---|---|---|---|
| **Follow** a team | `arbitrium:followedTeams:v1` | team names | `+` chip beside the team name |
| **Favorite** a game | `arbitrium:favoriteGames:v1` | event ids | `☆` at the card's corner, plus a pinned left edge |

They answer different questions — every game a team plays, versus this one
matchup — so they get separate `My Teams` / `My Games` filters rather than one
merged chip. Merging them would make the two statements indistinguishable, and
no rule recovers which one a user meant.

Following is keyed by **team name** so it outlives the fixture that prompted it;
pinning is keyed by **event id** and says nothing about either team.

`arbitrium:favorites:v1` predates the split. `migrateLegacyFavorites()` renames
it onto the followed-teams key and deletes it, which makes the migration
self-idempotent — once gone it cannot resurrect an old list after someone
unfollows everything. Parsing is fenced separately from the removal so a corrupt
value cannot make the migration retry on every page load.

Recently-viewed lives at `arbitrium:recent:v2`.

## The price flash

`usePriceFlash` diffs the executable Kalshi book (bid/ask per outcome) between
polls and flashes only the cards that actually moved. Nothing flashes on first
load, because there is no previous poll to compare against and inventing one
would make the first render lie. Since the backend's dedup trigger only stores
genuine price changes, a flash always means a real move.

## Live-data surfaces

Three things on the page are driven by real stored history, not decoration:

- **Activity ticker** (footer strip) — recent price moves from `/activity`, an
  endpoint added for this: neither `/divergences` (no change timestamps) nor
  `/events/{id}/history` (one event per request) can answer "what just moved?".
  Both of its queries are index-backed and measured under 2ms, so there is no
  cache. **Arbitrage appearances are the exception** and are labelled as such:
  arbitrage is computed on read and never stored, so there is no history of when
  one opened. Those entries are detected across polls in the current session
  only, and the UI says so.
- **Health indicator** (header) — per-source freshness from `/health`, with the
  poll interval in the tooltip so a slow-but-correct schedule is
  distinguishable from a wedged poller.
- **"Interesting right now"** — biggest reachable edge and open arbitrage from
  the divergences payload already fetched; biggest 24h swing from `/activity`.
  Auto-curated, and a slot with nothing to show says so rather than promoting
  the least-bad option.

## Design system

Tokens live at the top of `src/app/globals.css` and are exposed to Tailwind v4
through `@theme`. Colour has one governing rule: **crimson means signal, not
danger** — value and gains are crimson, their absence is a cool slate, and amber
is reserved for uncertainty.

The two chart series (`--series-kalshi`, `--series-consensus`) are validated
against the chart surface for the dark-mode lightness band, chroma floor,
protan/deutan separation and contrast. Re-run a palette validator before
changing them; they are not free-choice brand colours.
