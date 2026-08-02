# MarketEdge

> An independent auditor for two sports-pricing systems that never check each other's work.

MarketEdge sits on top of **Kalshi** (a CFTC-regulated prediction market, where price = collective
trader positioning) and **traditional sportsbooks** (fixed odds set by a bookmaker's risk team). It
detects meaningful divergences between them, ranks bet/combo opportunities by calibrated expected
value and risk tier, and — critically — grades its own historical accuracy so every recommendation
ships with an honest confidence number.

**This is not a Kalshi clone and not a "pick winners" betting bot.** Kalshi is a market; a sportsbook
is a bookmaker. Neither one tells you whether its own price is trustworthy, whether it disagrees with
anyone else's price, or whether trusting it has historically paid off. MarketEdge is the analysis
layer that requires having both sources in one place to build, and that neither platform has an
incentive to build for itself. Calibration and honesty about uncertainty are first-class features,
not afterthoughts.

## Design principles

These are baked into the code, not just the UI copy:

1. **Never hide uncertainty.** Low-confidence signals are shown with clear badges, not filtered out silently.
2. **"Safe" and "max payout" are different axes** and are never claimed to be simultaneously optimal. The optimizer exposes an explicit risk-tier choice rather than pretending one combo is both.
3. **Every probability is traceable to a calibration number,** not just a raw model output.
4. **Independence assumptions are stated explicitly** wherever joint probability is computed.
5. **Append-only history everywhere.** This is what makes CLV and calibration possible; no migration or refactor may introduce overwrites to snapshot tables.
6. **This system is an independent auditor, not a market-participant clone.** The entire value is in comparing Kalshi against a second, independent source.

## Status

**Phase 2 — Sportsbook ingestion and divergence scoring: complete**, verified end to end against
live NFL data. Both sources ingest on independent schedules and merge into one event row regardless
of poll order; `/divergences` reports four independent axes with nothing blended into a single
score. See [what shipped](#phase-2-what-shipped) below, including the gaps left open on purpose.

### Build order

| Phase | Scope | State |
|-------|-------|-------|
| 1 | Foundation: schema, Kalshi ingestion, normalization tests | **done** |
| 2 | Sportsbook ingestion, divergence scoring, `/divergences` | **done** |
| 3 | Outcome resolution, calibration + grading, `/performance` | **active** — resolution + job history shipped; calibration model next |
| 4 | Combo optimizer (3 risk tiers), `/combos` | planned |
| 5 | Frontend (dashboard, game detail, combo builder, performance) | planned |
| 6 | CI/CD, deploy, README polish | planned |

## Architecture (Phase 2)

```
Kalshi public API ──> ingestion/kalshi.py ────┐
                                              ├─> matching.py ──> events (one row per game,
The Odds API ──────> ingestion/odds_api.py ───┘                    dual-keyed)
                              │                                        │
                              └──> normalize.py ──> odds_snapshots ────┤
                                   (vig stripped)   (append-only)      │
                                                                       v
                       scheduler/flows.py (Prefect)          divergence/engine.py ──> /divergences
```

- **Ingestion:** Python + httpx, scheduled via Prefect.
- **Storage:** PostgreSQL. `odds_snapshots` is append-only; a `BEFORE INSERT` trigger suppresses
  rows whose price is unchanged since the last observation for the same `(event, source, outcome)`.
  Snapshots are written via Core executemany, never the ORM unit of work — an `INSERT ... RETURNING`
  miscounts its rows when the trigger suppresses one and aborts the whole flush.
- **Matching:** both ingestion paths run the same matcher before inserting, so whichever source polls
  first creates the event and the other merges into it. Poll order is not load-bearing.
- **Divergence:** Kalshi vs sportsbook consensus, joined on `team` (never home/away, which is
  provisional for Kalshi). Events that can't be scored — one source, or a consensus over fewer than
  `MIN_CONSENSUS_BOOKS` bookmakers — are returned with an explicit status and no number, rather than
  filtered out. Two independent axes are reported and never collapsed:
  `divergence` (vig-stripped mids — how far apart the two sources' *beliefs* are, and the input
  Phase 3 calibration needs) and `net_edge_after_spread` (consensus vs Kalshi's *raw executable*
  bid/ask — what is actually capturable). On live NFL data these rank differently, and roughly half
  of all real divergences are smaller than the spread required to capture them.
- **Ingest health:** every pass reports rows *written*, not attempted — the dedup trigger makes those
  wildly different numbers. Consecutive failures escalate with an `INGEST_UNHEALTHY` log marker;
  `/health` independently reports per-source write recency straight from the append-only table, so a
  dead poller still surfaces after a restart clears in-process counters.
- **Outcome resolution:** results come from The Odds API scores endpoint, joined on the odds event id
  we already store (and falling back to the shared matcher for Kalshi-only events). A result is
  stored as `winner_team` — a canonical team name — never as `'home'`/`'away'`; `winner_side` is a
  Postgres *generated* column, so a later home/away correction recomputes it in the same statement
  and the two can never drift. Resolution is the one **perishable** job here: the endpoint reaches
  back only 3 days, so an outcome missed inside that window is gone permanently, and `/health`
  reports `hours_until_next_data_loss` rather than waiting to report the loss.
- **Adaptive polling:** the Odds API bills per request returning events against a 500/month budget.
  A flat 15-minute interval cost ~96 credits/day and exhausted the month in five days. Polling is now
  paced by time-to-kickoff (hourly inside 24h, 6-hourly inside a week, daily beyond), because CLV is
  measured against the *closing* line — so credits go where prices actually move. A quota guard stops
  paid calls above a reserve so exhaustion cannot masquerade as a quiet market.
- **Job history:** `ingest_runs` records every pass in its own committed transaction, so a *failed*
  pass still leaves evidence. Data freshness alone could never separate "poller dead" from "market
  genuinely quiet"; a run row can.
- **API:** FastAPI: `/health`, `/divergences`.

## Phase 2: what shipped

**Ingestion.** The Odds API v4 h2h odds for NFL/NBA, verified against the live payload before being
trusted. Per-book American prices are vig-stripped individually, then combined by **median** (not
mean) so one mispriced book cannot drag the consensus. Raw per-book odds are preserved in
`order_book_depth` — which is what makes arbitrage detectable at all.

**Matching.** One game becomes one `events` row no matter which source sees it first. Matching is on
`(sport, unordered team pair)` disambiguated by start-time proximity, never by date equality: the two
sources legitimately disagree on the calendar date (Kalshi carries the originally-scheduled date,
The Odds API the current kickoff, and night games cross UTC midnight). Both ingestion paths run the
same matcher, so poll order is not load-bearing. Ambiguous matches (doubleheaders) are never guessed.

**Divergence scoring — four independent axes, never blended:**

| Axis | Question it answers | Priced off |
|------|--------------------|------------|
| `divergence` | How far apart are the two sources' *beliefs*? | vig-stripped mids |
| `net_edge_after_spread` | What survives crossing Kalshi's book? | raw executable bid/ask |
| `expected_value_at_depth` | Is the trade worth *money*, not just a good rate? | edge × resting size |
| `is_arbitrage` | Is there a risk-free position needing no belief at all? | raw odds, best book per outcome |

These genuinely disagree, which is the point. On live data the largest divergence ranked 5th by net
edge, and the leg with the *lower* percentage edge was worth ~4× more in dollars. Arbitrage is kept
strictly separate from net edge: a net edge pays only if the sportsbook consensus is the better
estimate, while an arbitrage pays regardless of outcome. `gross_profit` models **no fees and no
execution risk** and is an upper bound, not a return.

**Monitoring.** Every ingest pass reports rows *written*, not attempted. Consecutive failures escalate
with an `INGEST_UNHEALTHY` log marker; `/health` independently reports per-source write recency from
the append-only table, so a dead poller still surfaces after a restart clears in-process counters.

### Deferred on purpose

* **Reciprocal merge is unit-tested, not production-exercised.** All 16 live matches happened to
  agree with Kalshi's provisional home/away, so the authoritative-flip path has not yet run on real
  data. Awaiting a real doubleheader / postponement to exercise it.
* **`ingest_runs` table deferred to Phase 3**, where calibration wants job history anyway. Until
  then, "poller dead" vs "market genuinely quiet" is a heuristic rather than an exact answer.
* **NFL preseason has no sportsbook coverage.** The Odds API's `americanfootball_nfl` key is
  regular-season only, so Kalshi preseason games stay `single_source_no_divergence` by design rather
  than being silently omitted. Adding `americanfootball_nfl_preseason` would close it, at quota cost.
* **`liquidity_score` is a constant 0.** Kalshi's `liquidity_dollars` reports 0 on every observed
  market. The column keeps its original meaning rather than being redefined; real depth is a separate
  derived `resting_depth` from the bid/ask sizes.
* **No fee model.** Small gross arbitrages are very likely negative after Kalshi's trading fees.
  Modelling them needs real per-venue fee data; a wrong fee model would be worse than an honest gross
  figure with a stated caveat.

## Running locally

```bash
cp .env.example .env
docker compose up --build          # starts postgres, api, scheduler

# Apply migrations (run from the repo root inside the container, where the
# db/migrations tree and DATABASE_URL are both available):
docker compose run --rm --workdir /app api \
    alembic -c db/migrations/alembic.ini upgrade head

# Run the normalization tests (default workdir is /app/backend):
docker compose run --rm api pytest
```

## Out of scope for v1 (future work)

- **Player props / game-specific stats.** These need a line + direction (not a binary probability),
  player-ID matching across sources, and materially harder correlation handling. v1 is **team
  moneylines only.** If extended later, add nullable `player_id`/`line` columns to `odds_snapshots`
  rather than a new table.
- **Live / in-play websocket tracking.** v1 is pre-game, polling-based only.
- **Broad multi-sport support.** Start narrow (1–2 sports), expand once the pipeline is proven.
