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

**Phase 1 — Foundation (in progress).** Repo scaffold, Docker Compose, Postgres schema/migrations,
Kalshi ingestion, and normalization tests. See the build order below.

### Build order

| Phase | Scope | State |
|-------|-------|-------|
| 1 | Foundation: schema, Kalshi ingestion, normalization tests | **active** |
| 2 | Sportsbook ingestion, divergence scoring, `/divergences` | planned |
| 3 | Outcome resolution, calibration + grading, `/performance` | planned |
| 4 | Combo optimizer (3 risk tiers), `/combos` | planned |
| 5 | Frontend (dashboard, game detail, combo builder, performance) | planned |
| 6 | CI/CD, deploy, README polish | planned |

## Architecture (Phase 1)

```
Kalshi public API ──> ingestion/kalshi.py ──> normalize.py ──> odds_snapshots (append-only)
                                                                       │
                       scheduler/flows.py (Prefect, polling)           └─> events (metadata + resolution)
```

- **Ingestion:** Python + httpx, scheduled via Prefect.
- **Storage:** PostgreSQL. `odds_snapshots` is append-only; a `BEFORE INSERT` trigger suppresses
  rows whose price is unchanged since the last observation for the same `(event, source, outcome)`.
- **API:** FastAPI (Phase 1 exposes `/health` only; data endpoints land in Phase 2+).

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
