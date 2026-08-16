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
export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let event = null;
  try {
    event = (await fetchEvent(id)).event;
  } catch {
    event = null;
  }

  const rec = event?.recommendation ?? null;
  const away = event?.away_team ?? null;
  const home = event?.home_team ?? null;

  const headline = rec
    ? `Buy ${rec.side.toUpperCase()} ${teamVisual(rec.team)?.short ?? rec.team}`
    : event
      ? "No recommendation"
      : "Arbitrium";

  const price = rec ? `${Math.round(rec.price * 100)}¢` : null;

  const sub = rec
    ? `${event?.n_books ?? 0} sportsbooks price this nearer ${Math.round(
        rec.fair_value * 100,
      )}¢ · directional bet, pays $1 or nothing`
    : event
      ? "Kalshi and the sportsbooks agree, or too few books have posted a line."
      : "Kalshi vs sportsbook consensus";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#0a0b0d",
          padding: 64,
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", fontSize: 26, color: "#6d747f", letterSpacing: 1 }}>
            {(event?.sport ?? "").toUpperCase() || "ARBITRIUM"}
          </div>
          <div style={{ display: "flex", fontSize: 46, color: "#eceef1", fontWeight: 600 }}>
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
                color: rec ? "#e33d5c" : "#a2a9b4",
              }}
            >
              {headline}
            </div>
            {price ? (
              <div style={{ display: "flex", fontSize: 62, fontWeight: 700, color: "#eceef1" }}>
                {price}
              </div>
            ) : null}
          </div>
          <div style={{ display: "flex", fontSize: 26, color: "#a2a9b4", maxWidth: 1000 }}>
            {sub}
          </div>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            borderTop: "1px solid #23272e",
            paddingTop: 24,
          }}
        >
          <div style={{ display: "flex", fontSize: 28, color: "#eceef1", fontWeight: 600 }}>
            Arbi<span style={{ color: "#e33d5c" }}>trium</span>
          </div>
          <div style={{ display: "flex", fontSize: 22, color: "#4b515a" }}>
            Kalshi vs sportsbook consensus · gross of fees
          </div>
        </div>
      </div>
    ),
    size,
  );
}
