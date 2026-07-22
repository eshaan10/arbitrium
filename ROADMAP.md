# MarketEdge: Project Implementation Roadmap

## Purpose

MarketEdge is an independent auditor that sits on top of two sports-pricing systems that never check each other's work — Kalshi (a CFTC-regulated prediction market, where price reflects collective trader positioning) and traditional sportsbooks (fixed odds set by a bookmaker's risk team). The system detects meaningful divergences between the two, ranks bet/combo opportunities by calibrated expected value and risk tier, and — critically — grades its own historical accuracy so every recommendation ships with an honest confidence number.

This is not a "pick winners" betting tool. The core value proposition is market-efficiency analysis with a self-reported track record, built to demonstrate production-grade system design: real-time ingestion, append-only data integrity, cross-source normalization, and a monitoring layer that proves the system works rather than merely presenting numbers.

---

## 1. Phase 1 — Foundation (Implemented)

### 1.1 Ingestion

- Kalshi public market API integration (no auth required for market-data reads)
- Restructured from flat `/markets` polling to `/events?with_nested_markets=true` — retrieves event metadata and grouped per-outcome markets in a single call
- Server-side series scoping (`KALSHI_SERIES_TICKERS`) plus a client-side ticker-pattern guard, so only configured single-game moneyline series are ingested — non-moneyline markets (multi-game, cross-category, parlay) are excluded by construction, not by exception handling
- Fail-safe default: an empty or misconfigured series list ingests nothing and logs a warning, rather than falling back to fetching every open market

### 1.2 Unified Normalization Pipeline

- `normalize_kalshi_event` strips vig across *N* independent per-outcome order books (N=2 for NFL/NBA moneylines, N=3 for soccer with a draw), replacing an earlier two-function split (binary vs. three-way) with one correct, generalized path
- Handles the real API's string-typed `*_dollars` price fields and cent-integer legacy fallback
- Canonical team registry (suffix code + stable UUID → canonical name) built once in Phase 1, reused by Phase 2 for cross-source team matching
- Event metadata (sport, league, matchup, provisional date) extracted directly from Kalshi's ticker structure and upserted before any snapshot insert

### 1.3 Append-Only Storage & Data Integrity

- PostgreSQL schema: `events`, `odds_snapshots`, `calibration_history` (the last populated starting Phase 3)
- `odds_snapshots` is strictly append-only — a `BEFORE INSERT` trigger (`skip_unchanged_snapshot`) suppresses consecutive duplicate prices via change-data-capture semantics (compares against the latest row per event/source/outcome, not a global uniqueness constraint), so genuine price oscillation is preserved for closing-line-value analysis while true no-ops are silently dropped
- Vig-stripping performed at ingestion time; original raw price and format preserved alongside the normalized probability for auditability
- Liquidity captured as resting order-book depth (the literal confidence signal), with supplementary raw signals (bid/ask sizes, cumulative volume, open interest) preserved separately in a JSONB field — deliberately not collapsed into a single number, so later confidence-scoring logic can combine them explicitly rather than the ingestion layer silently choosing one

### 1.4 Verification & Governance

- 38 automated tests (normalization math, dedup semantics, shape/series guards, liquidity precedence) — run for real inside the container, not mirrored manually
- End-to-end verification against a live production database: schema inspected directly, dedup trigger proven against both duplicate and oscillating price sequences via manual transaction, real NFL data confirmed landing with correct per-event probability sums (1.0000 across all outcomes)
- Every schema and architectural decision documented with its rationale (e.g., `BIGSERIAL` vs. `UUID` primary keys chosen by table growth rate, not convention)

---

## 2. Technology Stack Used (Phase 1)

- **Backend:** Python, FastAPI
- **Data sources:** Kalshi public API (implemented), The Odds API (Phase 2)
- **Storage:** PostgreSQL (Alembic migrations, hand-authored to encode the dedup trigger)
- **Orchestration:** Prefect (scheduled ingestion, retries, observability)
- **Containerization:** Docker Compose (postgres, api, scheduler services; frontend added Phase 5)
- **Dependency management:** uv

---

## 3. Storage Design Decisions

### 3.1 Why Append-Only for Odds Snapshots

- Snapshots are high-frequency, immutable observations of a moving price — the entire closing-line-value and calibration story depends on never losing or overwriting a historical price point
- A dedup trigger (not an application-level check) enforces this uniformly regardless of which process writes — ingestion job, backfill script, or manual repair — so the guarantee lives with the data, not scattered across callers

### 3.2 Why `events` Is the One Mutable Table

- Game metadata (scores, status, resolution) genuinely changes over an event's lifecycle and must be updatable
- Kept structurally separate from the append-only snapshot history via foreign key, so mutability is isolated to the one table that legitimately needs it

### 3.3 Why Raw Signals Are Preserved Alongside Normalized Values

- Every transformation (vig-stripping, liquidity scoring) that "cleans" a value also preserves the original — protects against the case where a normalization formula later proves wrong and needs auditing or recomputation without re-fetching from the source

---

## 4. Next Iteration — Remaining Phases (Planned)

| Phase | Focus Area | Key Deliverables |
|---|---|---|
| **2** | Second source & divergence | The Odds API ingestion; Kalshi ↔ sportsbook event/team matching (upgrades home/away from provisional to authoritative); divergence scoring; arbitrage detection; `/divergences` endpoint |
| **3** | Calibration | Event outcome resolution; isotonic-regression calibration model; `calibration_history` population; reliability curve and closing-line-value tracking; `/performance` endpoint |
| **4** | Combo optimizer | Joint-probability calculation across legs with explicit correlation warnings; risk-tiered recommendation (Safest / Balanced / Max Payout) rather than a single conflated "safe and maximal" output; optional Kelly-criterion sizing; `/combos` endpoint |
| **5** | Frontend | Next.js dashboard with sport-tab navigation (Kalshi-style); confidence visualized via opacity/saturation rather than binary badges; game detail, combo builder, and performance pages |
| **6** | Polish & deployment | GitHub Actions CI; Docker image build; deployment (API/DB to Railway or Fly.io, frontend to Vercel); README finalized with problem statement, architecture diagram, and design-principles section |

**Estimated duration:** 3–5 weeks per remaining phase, sequential; parallelization is limited since Phases 3 and 4 both depend on Phase 2's cross-source matching being authoritative.

---

## 5. Key Risks & Mitigation

**1. Scope Creep**
Risk: Expanding to player props, additional sports, or live in-play tracking before the core moneyline pipeline is proven.
Mitigation: Explicitly scoped out of v1 with documented rationale (schema shape, correlation complexity); revisit only once Phases 2–4 are stable on moneylines.

**2. Cross-Source Join Corruption**
Risk: Silently assuming an unverified home/away ordering convention when joining Kalshi and sportsbook data corrupts every downstream divergence calculation without any visible error.
Mitigation: Kalshi's provisional home/away assignment is explicitly labeled (`home_away_source = kalshi_provisional`) and only promoted to authoritative once cross-referenced against The Odds API's explicit team labels in Phase 2 — never hardcoded from an assumed convention.

**3. Overstated Confidence**
Risk: Presenting a divergence or combo recommendation as more trustworthy than the underlying data supports (e.g., treating thin-liquidity Kalshi markets the same as deep ones).
Mitigation: Liquidity is preserved as an honest, separate signal rather than smoothed away; every future combo or divergence output must ship paired with its historical calibration accuracy at that confidence band, not a bare probability.

**4. Conflating "Safe" and "Maximal"**
Risk: Framing the combo optimizer as producing one output that is simultaneously the safest and highest-payout choice — a mathematical impossibility for parlays.
Mitigation: Explicit risk-tier selection (Safest / Balanced / Max Payout) built into the Phase 4 design from the outset, not retrofitted after a misleading single-output version ships.

**5. Premature Complexity**
Risk: Introducing infrastructure (e.g., TimescaleDB, Redis caching) before real usage data justifies it.
Mitigation: Deferred until Phase 1 ingestion volume is observed in production; added only when growth patterns justify the operational overhead.

**6. Silent Data Corruption**
Risk: A parsing or schema bug (e.g., misreading API field names, JSON `null` vs. SQL `NULL`) passes code review but corrupts data silently in production.
Mitigation: Every ingestion bug found in Phase 1 was caught by running the actual test suite and inspecting live database rows directly — not by code review alone — and the same verification discipline (real data, not synthetic fixtures) carries into every subsequent phase.

---

## 6. Expected Outcomes

### Short-Term (Phase 1 — Complete)
- Verified, production-tested ingestion and normalization pipeline
- Real NFL market data flowing end-to-end with correct cross-book vig-stripping
- Zero silent data-integrity gaps: every discovered bug (price-field parsing, missing event metadata, liquidity semantics) was caught, fixed, and re-verified against live data before moving forward

### Mid-Term (Phases 2–4)
- A second, independent pricing source cross-referenced against Kalshi with authoritative team/event matching
- A calibration system that proves — with historical accuracy numbers, not just plausible math — whether the system's divergence signals are actually predictive
- A risk-aware recommendation engine that is mathematically honest about the safety/payout tradeoff

### Long-Term Vision
A deployed, portfolio-grade system that demonstrates:
- Real-time, multi-source data engineering with correct handling of independent order books and cross-source normalization
- Production data-integrity discipline (append-only history, dedup semantics, auditable transformations)
- A monitoring and self-grading layer — the single most differentiating piece of the project, since it requires the system to report honestly on its own track record rather than merely presenting output
