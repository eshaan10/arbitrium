# Arbitrium — Roadmap and Delivery Record

This document was originally a plan. It is now a record of what was actually
built, kept in the same phase structure so the difference between the two stays
visible. Where the delivered thing diverges from the plan, the divergence is
stated rather than quietly edited out.

Anything marked **Not built** is not built. Nothing here is aspirational unless
it says so.

---

## Phase 1 — Ingestion and storage · **Built**

**Delivered**

- Kalshi poller with team resolution against a canonical registry (32 NFL
  teams, keyed by Kalshi's stable `custom_strike` UUIDs rather than by name).
- A unified normalizer converting Kalshi cents, American odds, and decimal odds
  onto one implied-probability scale, with `raw_price` + `price_format`
  retained so nothing is lossy.
- `odds_snapshots`, append-only, with a Postgres trigger that suppresses a write
  when the price for `(event_id, source, outcome)` is unchanged.

**What changed from the plan.** The plan assumed snapshots would be written
through the ORM. They are written with Core `executemany` instead, because the
dedup trigger returns `NULL` to suppress a row and SQLAlchemy reads that as a
failed flush — see the outage below.

**Incident: the silent week-long outage.** Ingestion broke and looked healthy
for about a week. The trigger's `NULL` return broke the ORM flush, and the
failure produced no output anywhere. The fix was not just the write path; it
was deciding that ingestion needs *visibility that survives the process dying*.
Three independent layers now exist:

1. in-process counters on each run,
2. an `ingest_runs` table recording attempted vs written per job,
3. `/health` freshness derived from the append-only table itself, which keeps
   reporting a growing age through a crash loop.

The standing rule that came out of it: **a conditional write is never confirmed
by rowcount.** Confirm with `RETURNING`, or with a count delta.

---

## Phase 2 — Matching and divergence · **Built**

**Delivered**

- The Odds API poller, with the key redacted in all log output.
- Cross-source event matching on canonical team + kickoff window, with a
  reciprocal Kalshi-side merge so poll order doesn't matter.
- The divergence engine: margin-stripped consensus median, per-outcome
  divergence, and **net edge after spread** as a separate number.
- Expected value at depth, computed against the size actually resting on the
  book rather than an unlimited fill.
- Arbitrage detection off raw per-book prices, including the case with **no
  Kalshi leg** — reported, and explicitly labelled as untakeable here.
- Status labels for unscoreable events (`single_source_no_divergence`,
  `insufficient_consensus`, `incomparable_outcomes`), returned rather than
  filtered.

**What changed from the plan.** The plan had one "edge" number. It became two,
after it turned out that roughly half of measured divergences are smaller than
the spread required to capture them. Blending them would have made every card
overstate what was available. They are now never combined.

**Risk closed: the home/away join.** Snapshots originally joined on
`outcome` (`home`/`away`). Home/away is Kalshi's *provisional guess* until the
Odds API confirms it, so re-labelling an event would have silently re-pointed
every historical row attached to it — corrupting price history retroactively,
which is the one thing an append-only table exists to prevent. The join anchor
moved to canonical `team`, which never changes once written (migration 0005,
backfilled in 0006). `home_away_source` is exposed through the API so a reader
can tell a confirmed label from a provisional one.

**Bug: Kalshi's two price scales.** The live API returns `yes_bid_dollars` as a
string already on the 0–1 scale (`"0.2400"`); the legacy `yes_bid` is an integer
in cents (`24`). Reading the wrong field is a silent 100× error that still
yields a plausible-looking probability. The parser prefers the dollar fields,
falls back per field, and documents the units where they're read.

---

## Phase 3 — Resolution and calibration · **Built** (reporting gated)

**Delivered**

- Outcome resolution from the Odds API scores feed, with an **ESPN fallback**
  when the primary source has no result.
- A permanent-loss countdown: the scores endpoint only reaches back 3 days, so
  `/health` reports `hours_until_next_data_loss` — converting "something is
  wrong" into "you have N hours before this outcome is gone forever".
- `calibration_history`, recording what the system recommended, split by origin
  (`live` = genuinely prospective, `reconstructed` = backtest).
- The sample gate: below the floor a rate is **withheld entirely**, not shown
  with a caveat.
- Isotonic calibration curve, reliability bins, Wilson intervals, Brier score.
- Closing-line value, which needs no resolved outcomes at all and is therefore
  the only signal available early.
- `/performance`, presenting all three bodies of evidence separately.

**Current reality.** The gate is doing its job: with only a handful of resolved
games, `/performance` reports `insufficient sample` for nearly everything and
publishes no accuracy rate. That is the system working, not a gap.

**Bug: a duplicate-counting index.** `calibration_history` was unique on
`(event_id, subject_team, origin)`. A recommendation's side moves as prices
drift, so recording one game at two moments wrote two rows for one bet —
inflating `n` and shrinking every confidence interval. Since the sample gate
counts rows, this was the "two sides of a two-way market are one bet" error
arriving through the back door. Now one row per `(event_id, origin)`, with
`subject_team` kept as data rather than identity (migration 0009).

**Bug: writes reported as zero.** `record_prediction` tested `rowcount`, which
psycopg returns as `-1` for `ON CONFLICT` inserts regardless of outcome — so a
pass that wrote 21 rows reported 0, feeding both `IngestHealth` and
`ingest_runs`. The same confusion that hid the Phase 1 outage. Now confirmed
with `RETURNING`.

**Bug: a monitor calibrated against the wrong schedule.** `/health` judged the
Odds API against the flat 15-minute setting while the poller ran adaptively —
a threshold wrong by up to 96×, so a healthy poller was reported stale for most
of every week. The inverse of the Phase 1 outage, and equally corrosive: a
monitor that cries wolf stops being read. Fixed to use the interval actually in
force, and pinned by a test that fails on reversion.

---

## Phase 4 — Combo optimizer · **Not built**

**Intended scope.** Multi-leg positions ranked within an explicit risk tier
(safe / balanced / max payout), where the tier is a choice the user makes rather
than an optimum the system claims to find.

**What exists.** The `/combos` page shell: a working tier selector and the card
layout drawn with empty labelled slots, plus a written list of what every combo
will have to state. It is explicitly marked "not live yet". The empty slots are
deliberate — a mock combo with plausible team names and prices, on a page about
betting, is precisely the kind of realistic-looking fake this project refuses to
ship.

**Why it isn't built.** The honest version needs calibrated per-leg
probabilities from Phase 3, and there aren't enough resolved games to calibrate
against yet. Multiplying uncalibrated probabilities across three legs compounds
the error, and a combo card is where an overconfident number does the most
damage. Building the mechanics now would mean shipping a number that looks
authoritative and isn't.

**Preconditions before it starts**

1. Enough resolved games for `/performance` to publish a calibration curve at
   all — the same floor that already governs the rate.
2. An explicit, displayed independence assumption. Two games in the same
   division on the same weekend are not independent, and any combo that
   multiplies through must say so on its face.
3. Cost and payout shown separately, never as one blended figure — the same
   rule the stake simulator follows for directional bets.

---

## Phase 5 — Frontend · **Built**

**Delivered**

- Dashboard: date-grouped event list, sport tabs derived from the feed, search,
  filters, Simple/Advanced as a structural split rather than a CSS toggle.
- Event detail: both sources per outcome, recorded price history, per-book
  breakdown, fenced arbitrage panel.
- `/performance` rendering the API's own verdicts — the UI never decides for
  itself when a number is trustworthy.
- `/how-it-works` and `/about`; inline `?` explainers on card jargon.
- Live surfaces: an activity ticker from real stored price moves, a per-source
  health indicator, per-card 24h move chips.
- localStorage personalisation: **Follow** a team (`+`) and **Favorite** a game
  (star) as two independent lists, recently-viewed, and a "what changed since
  your last visit" comparison.
- Finished pinned games graded against the call that was live when pinned —
  right / wrong / push / not-graded, with **no hit rate computed**, because a
  handful of self-selected games cannot support one.

**Added to the backend for it.** `/activity` (recent real price movement — no
existing endpoint could answer "what just moved?" without N requests),
`/events/lookup` (resolved games by id, since `/divergences` scores only
scheduled events, so a pinned game vanishes at kickoff), and `/events/{id}`
(one event in whatever state it is in).

**Bug: a deep link that expired with its game.** The detail page resolved an
event out of the `/divergences` list, which scores only scheduled events — so
every link 404'd the instant its game kicked off, and the finished-games view
led nowhere. `/events/{id}` now answers from stored data: the live divergence
body while a game is scheduled, and afterwards the result plus each source's
last price at or before kickoff. A finished game is deliberately **not**
re-scored. Kalshi keeps trading after the whistle, so its last quote reflects a
market that already knows the score; presenting that as a closing line would
flatter every comparison drawn from it, and presenting an edge computed from it
would describe a trade that no longer exists. Both endpoints share one
serializer, so a list row and a deep link cannot disagree about the same game.

**Bug: a seven-hour clock.** Kickoff times used the platform's default
timezone. The server ran in UTC and the browser in the viewer's zone, so the
same game read `8:25 PM` server-side and `1:25 PM` in a Pacific browser — wrong
for the reader, and a hydration mismatch as well. Suppressing the warning would
have kept the wrong time. The server cannot learn the browser's zone, so the
first render (server and hydration alike) is pinned to one fixed zone and swaps
to the viewer's after mount; both carry a zone label, so the swap reads as a
correction. The relative "in 3d" beside it keeps its suppression — that one is
genuinely clock-dependent and coarse enough to be harmless, which is the
distinction the fix turns on.

**Notable frontend bugs found by looking at the running app**, all fixed: the
dashboard silently truncating at the API's default limit and misreporting every
count derived from it; a chart series that rendered invisibly because a
single-observation line draws no segment; a card-wide click target clipped dead
by `sr-only`'s `overflow:hidden`; a sub-cent price move printed as `▲0¢`; two
components sharing one query key with different limits; and a localStorage
migration that would have retried forever on a corrupt value.

**Scope is closed.** The frontend is feature-complete for now. Further UI work
is out of scope until explicitly reopened.

---

## Standing rules

These came out of specific failures and outrank convenience.

1. **Never confirm a conditional write by rowcount.** `RETURNING` or a count
   delta. Wrong twice; the first cost a week of data.
2. **Attempted is not written.** Any health surface that conflates them is
   lying in the direction that hides outages.
3. **A withheld number beats a caveated one.** A number that exists gets quoted
   regardless of the words next to it.
4. **Unscoreable is a result.** Report it with its reason; never filter it out.
5. **A monitor that cries wolf is as bad as one that stays silent.** Thresholds
   track the schedule actually in force.
6. **Two sides of a two-way market are one bet.** Count games, not rows.
