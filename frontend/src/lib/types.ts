/**
 * Hand-written mirror of the API response bodies.
 *
 * NOT generated from the OpenAPI schema, deliberately: every endpoint in
 * backend/arbitrium/api/main.py is annotated `-> dict`, so FastAPI publishes
 * no response schema and a generated type would come out as `unknown`. These
 * are transcribed from the dict literals in main.py and are the single place
 * this app encodes the API shape.
 */

/** Mirrors DivergenceStatus in backend/arbitrium/divergence/engine.py. */
export type DivergenceStatus =
  | "scored"
  | "single_source_no_divergence"
  | "insufficient_consensus"
  | "incomparable_outcomes";

export type Source = "kalshi" | "consensus";

/** Both sides are BUYS on Kalshi — 'no' is not a sell. */
export type Side = "yes" | "no";

export interface Recommendation {
  team: string;
  side: Side;
  price: number;
  fair_value: number;
  edge: number;
  wins_if: string;
  max_contracts: number | null;
  max_stake: number | null;
}

export interface ArbitrageLeg {
  team: string;
  venue: string;
  implied_price: number;
}

export interface Arbitrage {
  total_cost: number;
  /** Gross: before fees and execution risk. An upper bound, never a return. */
  gross_profit: number;
  limiting_depth: number | null;
  venues: string[];
  includes_kalshi: boolean;
  legs: ArbitrageLeg[];
}

export interface BestTrade {
  team: string;
  side: string | null;
  net_edge_after_spread: number | null;
  resting_depth: number | null;
}

export interface Outcome {
  team: string | null;
  kalshi_probability: number | null;
  consensus_probability: number | null;
  divergence: number | null;
  net_edge_after_spread: number | null;
  trade_side: string | null;
  spread: number | null;
  resting_depth: number | null;
  kalshi_bid: number | null;
  kalshi_ask: number | null;
  kalshi_ask_size: number | null;
  kalshi_bid_size: number | null;
  expected_value_at_depth: number | null;
  /** Raw American odds per bookmaker, vig included. */
  books: Record<string, number> | null;
  tradeable: boolean;
}

export interface Divergence {
  event_id: string;
  sport: string | null;
  league: string | null;
  home_team: string | null;
  away_team: string | null;
  scheduled_start: string;
  status: DivergenceStatus;
  reason: string | null;
  sources: Source[];
  n_books: number | null;
  home_away_source: string | null;
  kalshi_event_ticker: string | null;
  odds_api_event_id: string | null;
  max_abs_divergence: number | null;
  best_net_edge: number | null;
  tradeable: boolean;
  recommendation: Recommendation | null;
  kalshi_series: string | null;
  best_expected_value: number | null;
  is_arbitrage: boolean;
  arbitrage: Arbitrage | null;
  best_trade: BestTrade | null;
  outcomes: Outcome[];
}

export interface DivergencesResponse {
  min_consensus_books: number;
  count: number;
  counts_by_status: Partial<Record<DivergenceStatus, number>>;
  tradeable_count: number;
  arbitrage_count: number;
  divergences: Divergence[];
}

export interface HistoryPoint {
  t: string;
  p: number;
}

export interface HistorySeries {
  source: Source;
  team: string | null;
  points: HistoryPoint[];
}

export interface EventHistory {
  event_id: string;
  home_team: string | null;
  away_team: string | null;
  series: HistorySeries[];
  total_points: number;
}

/* --- /performance ------------------------------------------------------- */

/** Mirrors SampleStatus in backend/arbitrium/calibration/sample.py. */
export type SampleStatus = string;

export interface ReliabilityBin {
  range: [number, number];
  n: number;
  mean_predicted: number | null;
  observed_rate: number | null;
  gap: number | null;
}

export interface CalibrationPoint {
  predicted: number;
  calibrated: number;
  n: number;
}

/**
 * A body of evidence with its sample gate attached. When `status` withholds
 * the rate, `accuracy` is null — the UI renders the verdict, it does not
 * decide for itself when a number is trustworthy.
 */
export interface GatedEvidence {
  label: string;
  n: number;
  status: SampleStatus;
  reason: string | null;
  accuracy: number | null;
  accuracy_95ci: [number, number] | null;
  brier_score: number | null;
  reliability_bins: ReliabilityBin[];
  calibration_curve: CalibrationPoint[] | null;
}

export interface ClvSummary {
  n: number;
  mean_clv: number | null;
  beat_close: number | null;
  beat_rate: number | null;
}

export interface PerformanceResponse {
  thresholds: {
    min_report_samples: number;
    min_fit_samples: number;
    trusted_samples: number;
  };
  source_reliability: Record<string, GatedEvidence>;
  track_record: Record<string, GatedEvidence>;
  closing_line_value: Record<string, ClvSummary>;
  note: string;
}

/* --- /combos (Phase 4, not yet implemented server-side) ------------------ */

export type RiskTier = "safe" | "balanced" | "max_payout";

export interface ComboLeg {
  event_id: string;
  team: string;
  side: Side;
  price: number;
  calibrated_prob: number;
}

export interface Combo {
  id: string;
  tier: RiskTier;
  legs: ComboLeg[];
  joint_probability: number;
  /** Stated explicitly wherever joint probability is computed. */
  independence_assumption: string;
  total_cost: number;
  payout: number;
}

/* --- /activity ----------------------------------------------------------- */

export interface ActivityChange {
  event_id: string;
  sport: string | null;
  home_team: string | null;
  away_team: string | null;
  source: Source;
  team: string | null;
  from: number;
  to: number;
  delta: number;
  at: string;
}

export interface ActivityMover {
  event_id: string;
  sport: string | null;
  home_team: string | null;
  away_team: string | null;
  team: string | null;
  /** Widest observed spread of prices in the window. */
  swing: number;
  changes: number;
}

export interface ActivityResponse {
  since: string;
  window_hours: number;
  changes: ActivityChange[];
  movers: ActivityMover[];
  counts: { changes: number; movers: number };
}

/* --- /health ------------------------------------------------------------- */

export interface SourceFreshness {
  last_write_at: string | null;
  age_seconds: number | null;
  stale: boolean;
  stale_after_seconds: number;
  /** The interval actually in force — adaptive for the Odds API. */
  poll_interval_seconds: number;
}

export interface HealthResponse {
  status: string;
  database: string;
  ingestion: Record<string, SourceFreshness>;
  resolution: {
    pending: number;
    verdict: string;
    hours_until_next_data_loss: number | null;
  };
}

/* --- /events/lookup ------------------------------------------------------ */

/**
 * A bare event record, available regardless of status — the only way to find
 * out what happened to a game once it leaves /divergences.
 */
export interface EventRecord {
  event_id: string;
  sport: string | null;
  league: string | null;
  home_team: string | null;
  away_team: string | null;
  scheduled_start: string;
  status: string;
  /** Null for a draw, and null while still unresolved. Never inferred. */
  winner_team: string | null;
  home_score: number | null;
  away_score: number | null;
  resolved_at: string | null;
  resolution_source: string | null;
  /** Set when the result window closed before an outcome could be collected. */
  unresolvable_reason: string | null;
}

export interface EventsLookupResponse {
  count: number;
  events: EventRecord[];
}
