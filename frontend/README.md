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

## Design system — terminal amber

Tokens live at the top of `src/app/globals.css` and are exposed to Tailwind v4
through `@theme`. Colour has one governing rule: **amber means signal, not
decoration** — a recommendation, an arbitrage and a gain are amber; a negative
metric, a losing leg and an unscoreable event drop to warm grey. An accent that
appears on good and bad numbers alike stops meaning anything.

Every neutral carries a warm undertone so amber is the only warm thing on the
page. Three channels sit outside the accent because they make statements amber
cannot: `--warn` (a muted rust: thin data, provisional), `--status-ok` (a
teal-green: the system is alive), and `--series-consensus` (a low-chroma slate,
the one deliberate cool exception — see below).

**Typography carries the identity as much as the colour, and the split is a
DEFAULT rather than a per-element choice.** Mono is the body default:
everything the system measured or named — prices, counts, team names, book
names, status words, timestamps, section labels, buttons, tabs. Sans is opt-in
via `.prose`, and only for long-form prose a person wrote: the landing
explainer, the About and How-it-works body, the sentences explaining what a
number does not mean.

Making mono the default is what keeps it consistent. An earlier version opted
*in* to mono per element, so anything overlooked fell back to sans — which is
how the rail's tile labels ended up sans while the values beneath them were
mono. Now anything overlooked is mono, which is the intended default, and the
exceptions are a short enumerable list.

Two deliberate exceptions to the monochrome, both identity rather than signal:
team logos and the 2px accent bar beneath each one. Those say *which game this
is*; they are never used to say a number is good.

### The palette is enforced, not documented

`src/lib/palette.test.ts` parses `globals.css` and fails the build on: text
contrast, the confidence-fade floor still being readable, protan/deutan
separation of the two chart series, any semantic channel collapsing into the
accent, and any grey drifting cool. The OpenGraph image duplicates the palette
by necessity (`ImageResponse` has no stylesheet) and is pinned against the same
source.

This exists because the previous system's chart colours were *documented* as
validated and then hand-tuned twice, with nothing to catch it — the validator
lived in a scratch file that was never committed. Colour maths is in
`src/lib/color.ts`, written longhand and shared with nothing the app renders,
so a bug cannot agree with itself.

## The list defaults to what you can act on

The feed is ~300 events of which ~270 cannot be scored, so **Recommended is the
landing view**, not All. Nothing is hidden by that: every other view is one chip
away with its count visible, and an empty Recommended says so plainly — "nothing
clears the spread right now" is a real answer, not a failure.

Within All, unscoreable events **fold into one disclosure per date group**
stating the count and the reasons ("14 games can't be scored · 14 one source
only"). Expanding renders compact rows rather than cards: twelve full cards
would re-create the problem the fold exists to solve, and none of a card's
apparatus — price hero, stake simulator, evidence line — has anything to show
for an event that could not be scored.

This is deliberately not filtering. The standing rule is that an unscoreable
event is a *result* and must be reported with its reason; a summary that says
how many there are and why satisfies that, and one click restores every game
with its own reason attached. The fold is suppressed entirely where it would
make the app look broken instead of tidy — in the "Can't score" view, while a
search is active, and in My Teams / My Games. `src/lib/fold.test.ts` pins each
of those exclusions.

## Mobile

Real layouts, not shrunk desktop ones. The wide book matrix becomes one block
per book below `sm`, so a price is never separated from its book name. Charts
get more height on a phone, not less. Filter chips and sport tabs scroll
sideways inside their own box rather than wrapping and stealing rows from the
sticky toolbar.

Touch is treated as an input, not a screen width: `.tap` projects a 44px hit
area from a small control without resizing it, popovers open on tap and close
on an outside tap (`pointerdown`, and hover is gated on `pointerType === "mouse"`
so a synthesised hover cannot latch), and inputs are 16px below `sm` so iOS does
not zoom the viewport on focus.
