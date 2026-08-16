import { Dashboard } from "@/components/dashboard/Dashboard";
import { fetchDivergences, LIST_LIMIT } from "@/lib/api";
import { parseMode } from "@/lib/mode";
import type { View } from "@/components/dashboard/Controls";
import type { DivergencesResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

function parseView(v: string | string[] | undefined): View {
  // `favorites` predates the follow/favorite split; it meant "teams I care
  // about", so a link shared before the split still lands somewhere true.
  if (v === "favorites") return "my-teams";
  return v === "recommended" ||
    v === "arbitrage" ||
    v === "unscoreable" ||
    v === "my-teams" ||
    v === "my-games"
    ? v
    : "all";
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const sport = typeof sp.sport === "string" ? sp.sport : null;

  // First paint comes from the server so the list is in the HTML; the client
  // takes over polling from there. A backend that is down is an expected state
  // during Phase 3 work, so it degrades to the client's error path rather than
  // failing the render.
  let initialData: DivergencesResponse | null = null;
  try {
    initialData = await fetchDivergences({ sport: sport ?? undefined, limit: LIST_LIMIT });
  } catch {
    initialData = null;
  }

  return (
    <Dashboard
      initialData={initialData}
      sport={sport}
      mode={parseMode(sp.mode)}
      view={parseView(sp.view)}
      /* Reading the clock is impure by definition, and the whole point is to
         hand the client the exact instant this request rendered so date
         grouping cannot disagree across the hydration boundary. This is a
         per-request server render, not a memoizable client component. */
      // eslint-disable-next-line react-hooks/purity
      serverNow={Date.now()}
    />
  );
}
