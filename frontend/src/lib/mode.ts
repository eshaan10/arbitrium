/**
 * Simple vs Advanced.
 *
 * Held in the URL rather than component state so a shared link carries the
 * reader's framing with it, and so the server can render the right shape on
 * the first paint instead of flashing Simple and then swapping.
 */
export type Mode = "simple" | "advanced";

export function parseMode(value: string | string[] | undefined): Mode {
  return value === "advanced" ? "advanced" : "simple";
}
