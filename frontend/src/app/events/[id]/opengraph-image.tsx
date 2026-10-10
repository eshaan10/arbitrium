import { readFile } from "node:fs/promises";
import { join } from "node:path";
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
/**
 * The app's two faces, vendored under src/assets/fonts (OFL, licences beside
 * them). next/font cannot reach this sandbox, so without these the preview
 * would fall back to a generic face and the wordmark would not match the
 * header. WOFF rather than WOFF2: satori does not decode WOFF2.
 */
const FONT_DIR = join(process.cwd(), "src/assets/fonts");
const fonts = Promise.all([
  readFile(join(FONT_DIR, "Inter-400.woff")),
  readFile(join(FONT_DIR, "Inter-500.woff")),
  readFile(join(FONT_DIR, "Unbounded-400.woff")),
]).then(([inter400, inter500, unbounded]) => [
  { name: "Inter", data: inter400, weight: 400 as const, style: "normal" as const },
  { name: "Inter", data: inter500, weight: 500 as const, style: "normal" as const },
  { name: "Unbounded", data: unbounded, weight: 400 as const, style: "normal" as const },
]);

export const PALETTE = {
  bg: "#0a0b0d",
  text: "#f2f3f0",
  dim: "#b9bcc4",
  muted: "#9a9ea6",
  faint: "#7d818a",
  border: "#25272b",
  signal: "#c6f432",
} as const;

/** The header's wordmark, drawn again: "arbitrium" in Unbounded, then a lime "/". */
function Wordmark({ size: px }: { size: number }) {
  return (
    <div style={{ display: "flex", fontFamily: "Unbounded", fontSize: px, color: PALETTE.text }}>
      arbitrium
      <span style={{ color: PALETTE.signal }}>/</span>
    </div>
  );
}

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

  const short = rec ? (teamVisual(rec.team)?.short ?? rec.team) : null;
  const yes = rec?.side === "yes";

  // The card's own words: the pick in plain language, then the exact order.
  const headline = rec
    ? `${short} to ${yes ? "win" : "lose"}`
    : !event
      ? null
      : d
        ? "No recommendation"
        : "Final";

  const order = rec ? `Buy ${yes ? "Yes" : "No"} · ${Math.round(rec.price * 100)}¢` : null;

  const sub = rec
    ? `Pays $1 if they ${yes ? "win" : "lose"}. ${d?.n_books ?? 0} sportsbooks say ${Math.round(
        rec.fair_value * 100,
      )}¢. A directional bet: it pays $1 or nothing.`
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
          fontFamily: "Inter",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", fontSize: 26, color: PALETTE.muted }}>
            {(event?.league ?? event?.sport ?? "").toUpperCase() || "Kalshi vs sportsbooks"}
          </div>
          <div style={{ display: "flex", fontSize: 44, fontWeight: 500, color: PALETTE.text }}>
            {away && home ? `${away} @ ${home}` : "Two places price the same games."}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {headline ? (
            <div
              style={{
                display: "flex",
                fontFamily: "Unbounded",
                fontSize: 76,
                letterSpacing: -1,
                color: rec ? PALETTE.text : PALETTE.dim,
              }}
            >
              {headline}
            </div>
          ) : (
            <Wordmark size={96} />
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
            {order ? (
              <div
                style={{
                  display: "flex",
                  fontSize: 30,
                  fontWeight: 500,
                  color: PALETTE.bg,
                  background: PALETTE.signal,
                  borderRadius: 10,
                  padding: "6px 16px",
                }}
              >
                {order}
              </div>
            ) : null}
            <div style={{ display: "flex", fontSize: 26, color: PALETTE.dim, maxWidth: 820 }}>
              {sub}
            </div>
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
          <Wordmark size={30} />
          <div style={{ display: "flex", fontSize: 22, color: PALETTE.faint }}>
            Kalshi vs sportsbook consensus · gross of fees
          </div>
        </div>
      </div>
    ),
    { ...size, fonts: await fonts },
  );
}
