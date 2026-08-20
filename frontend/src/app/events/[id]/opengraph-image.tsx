import { ImageResponse } from "next/og";
import { fetchEvent } from "@/lib/api";
import { teamVisual } from "@/lib/teams";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "Arbitrium event";

/**
 * The preview card that renders when a link is pasted into iMessage, Discord,
 * Slack, etc.
 *
 * Shows the matchup and the CURRENT recommendation, with the same language the
 * app uses — "Buy Yes" is a purchase, and the price is in cents. An event with
 * no recommendation says so rather than shipping a blank card, because the
 * absence of an edge is a real answer here.
 *
 * Rendered from live data at request time. If the API is unreachable the image
 * degrades to the wordmark instead of failing the whole share.
 */
/**
 * The palette, duplicated.
 *
 * `ImageResponse` renders in a satori sandbox with no stylesheet and no CSS
 * custom properties, so these cannot reference globals.css — they are the one
 * place in the app where a colour is written twice. Named rather than inlined
 * so the duplication is obvious, and pinned by a test that compares them back
 * against the stylesheet.
 */
export const PALETTE = {
  bg: "#0b0a09",
  text: "#f2ede4",
  dim: "#b3aa9c",
  muted: "#868075",
  faint: "#55504a",
  border: "#2a2521",
  signal: "#f2c14e",
} as const;

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let detail = null;
  try {
    detail = await fetchEvent(id);
  } catch {
    detail = null;
  }

  const event = detail?.event ?? null;
  // Null once the game has kicked off. A share preview is the most-forwarded
  // surface in the product, so a finished game says so rather than carrying a
  // price nobody can trade.
  const d = detail?.divergence ?? null;
  const rec = d?.recommendation ?? null;
  const away = event?.away_team ?? null;
  const home = event?.home_team ?? null;

  const headline = rec
    ? `Buy ${rec.side.toUpperCase()} ${teamVisual(rec.team)?.short ?? rec.team}`
    : !event
      ? "Arbitrium"
      : d
        ? "No recommendation"
        : "Final";

  const price = rec ? `${Math.round(rec.price * 100)}¢` : null;

  const sub = rec
    ? `${d?.n_books ?? 0} sportsbooks price this nearer ${Math.round(
        rec.fair_value * 100,
      )}¢ · directional bet, pays $1 or nothing`
    : !event
      ? "Kalshi vs sportsbook consensus"
      : d
        ? "Kalshi and the sportsbooks agree, or too few books have posted a line."
        : event.winner_team
          ? `${teamVisual(event.winner_team)?.short ?? event.winner_team} won · closing prices recorded`
          : "This game has finished · closing prices recorded";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: PALETTE.bg,
          padding: 64,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", fontSize: 26, color: PALETTE.muted, letterSpacing: 2 }}>
            {(event?.sport ?? "").toUpperCase() || "ARBITRIUM"}
          </div>
          <div style={{ display: "flex", fontSize: 46, color: PALETTE.text, fontWeight: 600 }}>
            {away && home ? `${away} @ ${home}` : "Arbitrium"}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
            <div
              style={{
                display: "flex",
                fontSize: 62,
                fontWeight: 700,
                color: rec ? PALETTE.signal : PALETTE.dim,
              }}
            >
              {headline}
            </div>
            {price ? (
              <div style={{ display: "flex", fontSize: 62, fontWeight: 700, color: PALETTE.text }}>
                {price}
              </div>
            ) : null}
          </div>
          <div style={{ display: "flex", fontSize: 26, color: PALETTE.dim, maxWidth: 1000 }}>
            {sub}
          </div>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            borderTop: `1px solid ${PALETTE.border}`,
            paddingTop: 24,
          }}
        >
          <div style={{ display: "flex", fontSize: 28, color: PALETTE.signal, fontWeight: 700 }}>
            ARBITRIUM
          </div>
          <div style={{ display: "flex", fontSize: 22, color: PALETTE.faint }}>
            Kalshi vs sportsbook consensus · gross of fees
          </div>
        </div>
      </div>
    ),
    size,
  );
}
