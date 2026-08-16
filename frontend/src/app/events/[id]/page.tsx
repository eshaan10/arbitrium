import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchEvent, fetchEventHistory } from "@/lib/api";
import { parseMode } from "@/lib/mode";
import { kalshiUrl, contextLine } from "@/lib/copy";
import { kickoff, pct, money, num } from "@/lib/format";
import { RecommendationLine } from "@/components/recommendation/RecommendationLine";
import { WhyThis } from "@/components/recommendation/WhyThis";
import { StakeSimulator } from "@/components/recommendation/StakeSimulator";
import { StatusExplainer } from "@/components/event/StatusExplainer";
import { RecordView } from "@/components/event/RecordView";
import { EventPin } from "@/components/event/EventPin";
import { recSignature } from "@/lib/changes";
import { OutcomeSection } from "@/components/event/OutcomeSection";
import { BooksTable } from "@/components/advanced/BooksTable";
import { ArbitragePanel } from "@/components/advanced/ArbitragePanel";
import { SectionHeading, Card } from "@/components/primitives";
import type { EventHistory } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * Per-event share metadata, so a link pasted into a chat renders the matchup
 * and the current call rather than a bare URL. The description mirrors the
 * card's own language — a preview that promised more than the page delivers
 * would be the most-shared dishonest surface in the product.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;

  let event = null;
  try {
    event = (await fetchEvent(id)).event;
  } catch {
    event = null;
  }

  if (!event) {
    return { title: "Event — Arbitrium" };
  }

  const matchup = `${event.away_team} @ ${event.home_team}`;
  const rec = event.recommendation;
  const description = rec
    ? `Buy ${rec.side} ${rec.team} at ${Math.round(rec.price * 100)}\u00A2 — ` +
      `${event.n_books ?? 0} sportsbooks price it nearer ${Math.round(rec.fair_value * 100)}\u00A2. ` +
      `Directional bet: pays $1 if it happens, nothing if it does not.`
    : `Kalshi and the sportsbook consensus do not currently disagree enough to act on.`;

  return {
    title: `${matchup} — Arbitrium`,
    description,
    openGraph: { title: matchup, description, type: "website" },
    twitter: { card: "summary_large_image", title: matchup, description },
  };
}

/** One metric with the sentence that keeps it from being misread. */
function Explain({
  name,
  value,
  negative,
  children,
}: {
  name: string;
  value: string;
  negative?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-border py-3 last:border-b-0">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-body text-text">{name}</span>
        <span
          className={`tabular text-body ${
            value === "—" ? "text-faint" : negative ? "text-neg" : "text-text"
          }`}
        >
          {value}
        </span>
      </div>
      <p className="mt-1 max-w-prose text-meta leading-relaxed text-muted">{children}</p>
    </div>
  );
}

export default async function EventPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const mode = parseMode(sp.mode);

  const { event: d, minConsensusBooks } = await fetchEvent(id);
  if (!d) notFound();

  // History is supplementary — the page is useful without it, so a failure
  // here degrades to a note rather than taking down the whole view.
  let history: EventHistory | null = null;
  try {
    history = await fetchEventHistory(id);
  } catch {
    history = null;
  }

  const kalshi = kalshiUrl(d.kalshi_series);
  const ctx = contextLine(d);

  return (
    <div className="space-y-5">
      <RecordView
        id={d.event_id}
        home={d.home_team}
        away={d.away_team}
        sport={d.sport}
        rec={recSignature(d)}
        arb={d.is_arbitrage}
      />

      <Link href="/" className="inline-block text-meta text-muted hover:text-dim">
        ← All events
      </Link>

      <div>
        <div className="text-micro uppercase tracking-[0.06em] text-muted">
          {[d.sport, d.league]
            .filter(Boolean)
            .map((s) => s!.toUpperCase())
            .filter((s, i, a) => a.indexOf(s) === i)
            .join(" · ")}{" "}
          · {kickoff(d.scheduled_start)}
        </div>
        <div className="mt-1 flex items-start gap-3">
          <h1 className="text-lede font-semibold">
            {d.away_team} <span className="font-normal text-muted">@</span> {d.home_team}
          </h1>
          <EventPin
            eventId={d.event_id}
            label={`${d.away_team} at ${d.home_team}`}
            rec={recSignature(d)}
          />
        </div>
        {/* Provenance: home/away is Kalshi's provisional guess until the odds
            feed confirms it, and the reader should know which they're seeing. */}
        {d.home_away_source && d.home_away_source !== "odds_api" ? (
          <p className="mt-1 text-meta text-warn">
            Home/away is provisional — inferred from Kalshi and not yet confirmed against the odds
            feed.
          </p>
        ) : null}
      </div>

      <Card className="p-4">
        <RecommendationLine d={d} minBooks={minConsensusBooks} size="lg" />
        <div className="mt-2.5">
          <WhyThis d={d} minBooks={minConsensusBooks} />
        </div>
        {ctx ? <div className="mt-2 text-meta text-muted">{ctx}</div> : null}
        {d.recommendation ? (
          <div className="mt-3">
            <StakeSimulator rec={d.recommendation} />
          </div>
        ) : null}
        {kalshi ? (
          <a
            href={kalshi}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-block text-meta text-signal-600 hover:text-signal"
          >
            ↗ Open on Kalshi
          </a>
        ) : null}
      </Card>

      <StatusExplainer d={d} minBooks={minConsensusBooks} />

      <div>
        <SectionHeading note="Both sources for each outcome, with the recorded price history. Only genuine price changes are stored.">
          Outcomes
        </SectionHeading>
        <div className="space-y-4">
          {d.outcomes.map((o) => (
            <OutcomeSection key={o.team ?? "draw"} outcome={o} history={history} />
          ))}
        </div>
      </div>

      {mode === "advanced" ? (
        <>
          <div>
            <SectionHeading note="The numbers behind the recommendation, and what each one does not mean.">
              What the numbers mean
            </SectionHeading>
            <Card className="px-4 py-1">
              <Explain name="Divergence" value={pct(d.max_abs_divergence)}>
                How far apart the two sources&apos; vig-stripped beliefs are. This is the input
                calibration needs — it is <em>not</em> money, and roughly half of real divergences
                are smaller than the spread required to capture them.
              </Explain>
              <Explain
                name="Net edge after spread"
                value={pct(d.best_net_edge)}
                negative={(d.best_net_edge ?? 0) < 0}
              >
                What survives crossing Kalshi&apos;s executable bid/ask. This is the capturable
                number. A large divergence with a negative net edge is a real measurement worth
                nothing.
              </Explain>
              <Explain
                name="Expected value at depth"
                value={money(d.best_expected_value)}
                negative={(d.best_expected_value ?? 0) < 0}
              >
                Value at the size actually resting on the book, not at an unlimited fill. It only
                pays if the sportsbook consensus is the better estimate — that premise is what
                the performance page is grading.
              </Explain>
              <Explain name="Consensus books" value={num(d.n_books)}>
                Bookmakers behind the median. Below {minConsensusBooks} the engine refuses to score
                the event rather than calling two books a consensus.
              </Explain>
            </Card>
          </div>

          {d.outcomes.some((o) => o.books) ? (
            <div>
              <SectionHeading>Every book</SectionHeading>
              <Card className="p-4">
                <BooksTable outcomes={d.outcomes} />
              </Card>
            </div>
          ) : null}
        </>
      ) : null}

      <ArbitragePanel d={d} />
    </div>
  );
}
