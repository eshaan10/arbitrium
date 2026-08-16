import type {
  ActivityResponse,
  DivergencesResponse,
  EventHistory,
  EventsLookupResponse,
  HealthResponse,
  PerformanceResponse,
} from "./types";

/**
 * On the server we talk to FastAPI directly. In the browser we go through the
 * Next route handler at /api/be, which keeps the backend URL server-side and
 * means FastAPI never needs a CORS policy for this app.
 */
export const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

function base(): string {
  return typeof window === "undefined" ? BACKEND_URL : "/api/be";
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
    // This is live market data; a cached divergence is a wrong divergence.
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    throw new ApiError(`${path} failed (${res.status})`, res.status);
  }
  return (await res.json()) as T;
}

/**
 * The backend defaults to 200 and caps at 1000. Taking the default silently
 * truncated the list AND every count derived from it — the dashboard reported
 * "200 events / 168 can't score" against a real 288 / 256. Ask for the cap so
 * the tiles describe the whole feed.
 */
export const LIST_LIMIT = 1000;

export interface DivergenceQuery {
  sport?: string;
  status?: string;
  minDivergence?: number;
  tradeableOnly?: boolean;
  limit?: number;
}

export function divergencesPath(q: DivergenceQuery = {}): string {
  const params = new URLSearchParams();
  if (q.sport) params.set("sport", q.sport);
  if (q.status) params.set("status", q.status);
  if (q.minDivergence != null) params.set("min_divergence", String(q.minDivergence));
  if (q.tradeableOnly) params.set("tradeable_only", "true");
  if (q.limit != null) params.set("limit", String(q.limit));
  const qs = params.toString();
  return `/divergences${qs ? `?${qs}` : ""}`;
}

export function fetchDivergences(q: DivergenceQuery = {}): Promise<DivergencesResponse> {
  return get<DivergencesResponse>(divergencesPath(q));
}

/**
 * Ask for the endpoint's maximum (it defaults to 400, caps at 2000). The rows
 * come back ordered by time across ALL sources, so a default-sized window on a
 * busy event would spend its budget on Kalshi ticks and cut the sparse
 * consensus observations off the end — losing a whole series rather than
 * shortening both.
 */
export function fetchEventHistory(eventId: string): Promise<EventHistory> {
  return get<EventHistory>(`/events/${eventId}/history?limit=2000`);
}

export function fetchPerformance(): Promise<PerformanceResponse> {
  return get<PerformanceResponse>("/performance");
}

export function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>("/health");
}

/** Resolved or otherwise non-scheduled events, by id. */
export function fetchEventsLookup(ids: string[]): Promise<EventsLookupResponse> {
  return get<EventsLookupResponse>(`/events/lookup?ids=${encodeURIComponent(ids.join(","))}`);
}

export function fetchActivity(hours = 24, limit = 40): Promise<ActivityResponse> {
  return get<ActivityResponse>(`/activity?hours=${hours}&limit=${limit}`);
}

/**
 * There is no GET /events/{id} carrying the divergence body — only the list
 * endpoint and a separate /events/{id}/history. So a deep link resolves by
 * pulling the list and selecting from it. That is one extra round trip on a
 * cold load and it warms the list cache for the back navigation; when the
 * backend grows a single-event endpoint, only this function changes.
 */
export async function fetchEvent(eventId: string) {
  const data = await fetchDivergences({ limit: LIST_LIMIT });
  const event = data.divergences.find((d) => d.event_id === eventId) ?? null;
  return { event, minConsensusBooks: data.min_consensus_books };
}

/** Query keys, in one place so invalidation can't drift from the fetchers. */
export const queryKeys = {
  divergences: (q: DivergenceQuery = {}) => ["divergences", q] as const,
  event: (id: string) => ["event", id] as const,
  history: (id: string) => ["history", id] as const,
  performance: () => ["performance"] as const,
  activity: (hours: number) => ["activity", hours] as const,
  lookup: (ids: string[]) => ["events-lookup", [...ids].sort().join(",")] as const,
  health: () => ["health"] as const,
};
