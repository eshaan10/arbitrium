import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "How it works — Arbitrium",
  description:
    "What Kalshi and sportsbook consensus are, what divergence and net edge mean, and why confidence and arbitrage are kept separate.",
};

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-20">
      <h2 className="text-title font-semibold text-text">{title}</h2>
      <div className="mt-2 space-y-3 text-body text-dim">{children}</div>
    </section>
  );
}

export default function HowItWorksPage() {
  return (
    <div className="max-w-[68ch] space-y-8">
      <div>
        <h1 className="text-lede font-semibold">How this works</h1>
        <p className="mt-2 text-body text-dim">
          Arbitrium watches two places that price the same games and never check each other&apos;s
          work. When they disagree, it says so — and, just as often, it says the disagreement
          isn&apos;t worth acting on.
        </p>
      </div>

      <Section id="two-sources" title="Two sources, priced differently">
        <p>
          <strong className="text-text">Kalshi</strong> is a prediction market. Its price is what
          traders are collectively willing to pay, and it moves whenever someone buys or sells. A
          contract pays $1 if the outcome happens and nothing if it doesn&apos;t, so a price of 40¢
          means the market thinks it&apos;s about 40% likely.
        </p>
        <p>
          <strong className="text-text">Sportsbooks</strong> set odds through a risk desk. Their
          number reflects what the book is willing to take, plus a built-in margin. We strip that
          margin out and take the median across every book that has posted a line — that median is
          what this site calls the <em>consensus</em>.
        </p>
        <p>
          Neither one tells you whether it&apos;s trustworthy, whether it disagrees with anyone
          else, or whether trusting it has historically paid. That gap is the entire point of this
          site.
        </p>
      </Section>

      <Section id="consensus" title="Consensus and the book count">
        <p>
          A consensus over two sportsbooks isn&apos;t a consensus. Below a floor, the engine refuses
          to score the event at all rather than publish a number built on one or two opinions —
          those games still appear in the list, labelled with the reason.
        </p>
        <p>
          More books agreeing is stronger evidence. Far from kickoff, most games have very few books
          posted, which is normal and not a failure.
        </p>
      </Section>

      <Section id="divergence" title="Divergence vs. net edge">
        <p>
          <strong className="text-text">Divergence</strong> is how far apart the two sources&apos;
          beliefs are. It is not money. To act on it you have to buy on Kalshi, and Kalshi has a
          spread — a gap between the price to buy and the price to sell.
        </p>
        <p>
          <strong className="text-text">Net edge</strong> is what survives after crossing that
          spread. It is the number that can actually be captured, and roughly half of all real
          divergences are smaller than the spread required to capture them. A big divergence with a
          negative net edge is a genuine measurement worth nothing.
        </p>
        <p>
          Both are shown, never blended into one score, precisely so neither can be mistaken for the
          other.
        </p>
      </Section>

      <Section id="confidence" title="Confidence">
        <p>
          Confidence is built from two independent things: how many sportsbooks agree, and how many
          contracts are actually resting at the price. Either can sink a signal on its own — a
          consensus over three books is thin, and an edge you can only take $5 of is not an
          opportunity.
        </p>
        <p>
          It deliberately ignores the <em>size</em> of the edge. Letting a big number raise
          confidence would make the weakest signals the loudest ones.
        </p>
      </Section>

      <Section id="arbitrage" title="Arbitrage is a different product">
        <p>
          Occasionally prices disagree enough that covering <em>every</em> outcome costs less than
          the $1 it pays out. That is arbitrage, and unlike a recommendation it does not depend on
          who wins.
        </p>
        <p>
          It is kept in its own panel and never used as a headline, because confusing the two would
          badly misprice the risk of an ordinary recommendation. It also usually requires an account
          on a second platform, and some arbitrages have no Kalshi leg at all — in which case they
          can&apos;t be taken here, and the site says so.
        </p>
        <p>
          Every arbitrage figure shown is <strong className="text-text">gross</strong>: before fees,
          and assuming both legs actually fill at the quoted prices.
        </p>
      </Section>

      <Section id="honesty" title="What this site will not do">
        <p>
          It will not hide an event it can&apos;t score, quote a win rate before enough games have
          resolved, or present a backtest as a live record. The{" "}
          <Link href="/performance" className="tap text-signal-600 hover:text-signal">
            performance page
          </Link>{" "}
          withholds a number entirely rather than publishing one with a caveat, because a number
          that exists gets quoted regardless of the words next to it.
        </p>
        <p>
          Nothing here is advice, and none of it is a guarantee. It is a second opinion on a price.
        </p>
      </Section>

      <div className="border-t border-border pt-5">
        <Link href="/" className="tap text-body text-signal-600 hover:text-signal">
          ← Back to the dashboard
        </Link>
      </div>
    </div>
  );
}
