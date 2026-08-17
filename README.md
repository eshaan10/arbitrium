# Arbitrium

Two systems price the same sports events and never check each other's work:
**Kalshi**, a CFTC-regulated prediction market where the price is what traders
will pay, and **sportsbooks**, whose odds are set by a risk desk and carry a
built-in margin. Arbitrium measures where they disagree, reports how much of
that disagreement is actually capturable after costs, and grades its own
accuracy honestly enough to tell you when it doesn't know.

The interesting problem was never picking winners. It was building something
that refuses to overclaim: that reports a number only when the sample supports
it, keeps a backtest visibly separate from a live record, and says "I can't
score this" rather than filling the space.

---

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Kalshi ingestion, normalizer, append-only storage | **Built** |
| 2 | Odds API ingestion, matching, divergence + arbitrage engine | **Built** |
| 3 | Outcome resolution, calibration, sample gating, `/performance` | **Built**, reporting withheld until the sample floor is met |
| 4 | Combo optimizer | **Not built** — see below |
| 5 | Next.js frontend | **Built** |

276 backend tests, 147 frontend tests. Every claim below is either covered by a
test or was verified against the live database.

---

## What it does

**Ingestion.** Two pollers on independent schedules. Kalshi runs flat at 5
minutes (a live order book moves constantly). The Odds API is adaptive —
hourly inside 24h of kickoff, four times a day inside a week, daily beyond that
— because the plan allows ~500 credits/month and a flat 15-minute interval
burns the entire budget in five days.

**Storage.** `odds_snapshots` is append-only. A Postgres trigger suppresses a
write when the price for `(event_id, source, outcome)` is unchanged, so the
table records genuine price *changes* rather than poll attempts. That is what
makes closing-line value measurable at all, and it is why a flat line in the UI
means the price genuinely held.

**Divergence.** For each scheduled event, the engine strips the bookmaker
margin, takes the median across every book that posted a line, and compares it
to Kalshi. It reports two numbers that are never blended:

- **divergence** — how far apart the two beliefs are.
- **net edge after spread** — what survives crossing Kalshi's executable
  bid/ask. Roughly half of real divergences are smaller than the spread needed
  to capture them, so a large divergence with a negative net edge is a real
  measurement worth nothing.

Events that cannot be scored are returned **with a status and a reason**, never
filtered out — a game with one bookmaker is a fact about our coverage, and
hiding it would let a caller assume the game doesn't exist.

**Arbitrage** is detected off raw per-book prices and kept in its own fenced
panel. It is the only place in the product allowed to use guaranteed-payout
language, because it is the only trade whose payout doesn't depend on who wins.
Every arbitrage figure is gross: before fees, assuming both legs fill.

**Calibration.** `/performance` grades three separate bodies of evidence and
never merges them: source reliability (is consensus actually the better
estimate?), track record split into `live` vs `reconstructed`, and closing-line
value. Below the sample floor a rate is **withheld entirely** rather than shown
with a caveat — a number that exists gets quoted regardless of the words next
to it.

---

## Bugs worth recording

These are in the history and in the tests. They are the reason several
now-boring parts of the codebase look the way they do.

**The silent week-long outage.** Snapshot writes went through the ORM, and the
dedup trigger returns `NULL` to suppress a row. SQLAlchemy interpreted that as
a failed flush; ingestion broke and *looked completely healthy* for about a
week, because the failure had no output. Fixed by moving to Core `executemany`
and, more importantly, by adding three independent layers of ingest visibility:
in-process counters, an `ingest_runs` job table, and a `/health` freshness
check derived from the append-only table itself, which keeps reporting a
growing age even through a crash loop.

**The same mistake, a second time.** Months later `record_prediction` reported
zero writes while actually writing 21 rows: it tested `rowcount`, which psycopg
returns as `-1` for `ON CONFLICT` inserts whether or not a row landed. Same
attempted-versus-written confusion, same two consumers. Conditional writes are
now confirmed with `RETURNING` or a count delta, never a rowcount.

**Kalshi's two price scales.** The live API returns `yes_bid_dollars` as a
*string* already on the 0–1 scale (`"0.2400"`), while the legacy `yes_bid` is an
integer in cents (`24`). Reading the wrong one is a silent 100× error that still
produces a plausible-looking probability. The parser prefers the dollar fields
and falls back per-field, with the units documented at the call site.

**The home/away join.** Snapshots were originally joined on `outcome`
(`home`/`away`). But home/away is Kalshi's *provisional guess* until the Odds
API confirms it, and re-labelling an event at the event level would silently
re-point every historical row. The join anchor moved to canonical `team`, which
never changes for a written row; the UI still surfaces `home_away_source` so a
reader knows which they're looking at.

**A duplicate-counting index.** `calibration_history` was unique on
`(event_id, subject_team, origin)` — but a recommendation's *side* moves as
prices drift, so recording the same game at two moments wrote two rows for one
bet. The sample gate counts rows, so that inflates `n` and shrinks every
confidence interval: the "two sides of a two-way market are one bet" error
arriving through the back door. Now one row per `(event_id, origin)`.

**A deep link that expired with its game.** The detail page resolved an event
by pulling `/divergences` and selecting from it — but that endpoint scores only
*scheduled* events, deliberately, so a saved link 404'd the moment its game
kicked off. The link rotted exactly when someone would open it: to find out what
happened. `GET /events/{id}` now answers from stored data, returning the live
divergence body while a game is scheduled and, afterwards, the result plus each
source's last price *at or before kickoff*. A finished game is never re-scored:
Kalshi keeps trading after the whistle, and a quote from a market that already
knows the score is not a closing line, let alone an edge.

**A seven-hour clock.** Kickoff times were formatted with the platform default
timezone, so the server rendered `8:25 PM` and a Pacific browser rendered
`1:25 PM` for the same game — wrong for the reader, and a React hydration
mismatch on the way. The server cannot know the browser's zone, so the first
render (server *and* hydration) is pinned to one fixed zone and swaps to the
viewer's after mount; both forms carry a zone label so the swap reads as a
correction rather than a glitch. A test moves the ambient zone around underneath
the formatter and fails if anyone reverts to platform-default formatting.

**A monitor that cried wolf.** `/health` judged the Odds API against the flat
15-minute setting while the poller ran on the adaptive schedule — a threshold
wrong by up to 96×, reporting a healthy poller as stale for most of every week.
This is the original outage inverted: there the monitor was silent while
ingestion was broken; here it alarmed while ingestion was fine. Both end with
nobody trusting the signal. Fixed to read the interval actually in force, with
a test that fails if anyone reverts it.

---

## Architecture

```
Kalshi API ─┐                          ┌─ /divergences   scored events + reasons
            ├─ pollers ─→ Postgres ─→ ─┼─ /events/{id}         one event, any state
Odds API ───┘  (adaptive) (append-only)├─ /events/{id}/history
ESPN (resolution fallback)             ├─ /events/lookup  resolved games by id
                                       ├─ /activity       recent real price moves
                                       ├─ /performance    gated self-grading
                                       └─ /health         per-source freshness
                                                │
                                          Next.js (SSR + polling)
```

**Backend** — Python 3.11, FastAPI, SQLAlchemy 2, Postgres 16, Alembic, httpx.
The scheduler is a single long-running process running four jobs on independent
intervals (Kalshi, Odds API, calibration, resolution).

**Frontend** — Next.js 16 (App Router), React 19, TypeScript, Tailwind v4,
TanStack Query, Recharts. The browser never calls FastAPI directly: server
components fetch it, and the client polls through a Next route handler that
forwards an allowlist of GET endpoints. Personalisation is localStorage only —
no accounts, nothing leaves the browser.

See [`frontend/README.md`](frontend/README.md) for the UI's own design rules,
and [`ROADMAP.md`](ROADMAP.md) for what each phase actually delivered.

---

## Setup

```bash
git clone https://github.com/eshaan10/Arbitrium.git
cd Arbitrium
cp .env.example .env          # add KALSHI_* and ODDS_API_KEY
docker compose up
```

- API — http://localhost:8000 (`/docs` for the schema)
- Frontend — http://localhost:3000
- Postgres — localhost:5432

Migrations run against `db/migrations` (Alembic). Tests:

```bash
docker compose exec api python -m pytest      # backend
cd frontend && pnpm test                      # frontend
```

The backend tests need a reachable database and run inside the `api` container.
`db_session` wraps each test in a transaction that is always rolled back, but it
does **not** hide existing rows — tests assert against their own fixtures, not
global counts.

---

## Not built: Phase 4, the combo optimizer

Multi-leg positions ranked within an explicit risk tier. The UI shell exists
(`/combos`) with the card shape and the tier selector, drawn with empty slots
and labelled "not live yet" — deliberately not a mock combo with plausible
teams and prices, which on a betting page is the one thing this product
shouldn't ship.

It is not built because the honest version depends on Phase 3 producing
calibrated per-leg probabilities, and there aren't enough resolved games yet to
calibrate against. Multiplying uncalibrated probabilities through three legs
compounds the error, and a combo card is exactly where an overconfident number
does the most damage. This is scope discipline, not abandonment: the endpoint
shape and the honesty rules it has to satisfy are written down in the roadmap.

---

## Future work: calibration-driven adaptive weighting

*Not started. Recorded here so the idea is on paper with its preconditions
attached.*

Today the consensus is an unweighted median across every book that posted a
line. Every book counts the same. It is plausible that some books are
systematically better predictors than others, and that weighting the consensus
by each book's measured historical accuracy would produce a sharper estimate
than the median.

It is deliberately gated on having enough resolved-game history to fit those
weights without overfitting. Per-book weights are a lot of free parameters
estimated from a small sample, and with a few dozen games the fit would mostly
be describing noise — producing a consensus that looks more precise while being
less accurate, and worse, one whose confidence intervals would understate the
error. The same sample-gate discipline that governs `/performance` applies:
this stays unbuilt until there is enough resolved history to test whether a
weighted consensus actually beats the median out of sample, and it ships only
if it does.

---

## What this project will not do

- Quote a win rate before enough games have resolved.
- Present a backtest as a live record.
- Hide an event it cannot score.
- Blend a divergence and a capturable edge into one number.
- Describe a directional bet with a single expected-value figure.

Nothing here is financial advice, and every figure is gross of fees and
execution risk. Not affiliated with Kalshi or any sportsbook.
