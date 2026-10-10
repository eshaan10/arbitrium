import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

/**
 * The favicon: the wordmark's lime "/" on the card surface.
 *
 * Generated rather than committed as a file, so it cannot drift from the
 * palette. The slash is a skewed bar, not a font glyph: at 16px a glyph's
 * hinting and side-bearings decide whether it reads, and a bar is exact.
 * Checked at 16px in a real browser before choosing it over "a/".
 */
export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0f1012",
          borderRadius: 7,
        }}
      >
        <div
          style={{
            width: 6,
            height: 24,
            background: "#c6f432",
            borderRadius: 1,
            transform: "skewX(-24deg)",
          }}
        />
      </div>
    ),
    size,
  );
}
