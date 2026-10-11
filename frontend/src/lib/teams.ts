import { TEAM_ALIASES, TEAM_VISUALS, type League, type TeamVisual } from "./teams.generated";

export type { League, TeamVisual };

/**
 * Logos are vendored under public/, not fetched from a third party at runtime,
 * one folder per league: ESPN abbreviations collide across leagues (atl, det,
 * hou, lac), so a flat folder would give the Hawks the Falcons' mark.
 */
export function logoPath(visual: TeamVisual): string {
  return `/logos/${visual.league}/${visual.abbr}.png`;
}

/** Canonical name first, then a known alternate spelling ("LA Clippers"). */
export function teamVisual(name: string | null | undefined): TeamVisual | null {
  if (!name) return null;
  return TEAM_VISUALS[name] ?? TEAM_VISUALS[TEAM_ALIASES[name] ?? ""] ?? null;
}

/**
 * Text colours for the initials badge of a team with no logo.
 *
 * Fixed and few rather than generated: each is held to 4.5:1 against
 * --surface-raised (the badge fill) by teams.badge.test.ts. Picked by a hash of
 * the name, so a team keeps its colour across renders and sessions; two teams
 * may share one, which the initials and the name beside them disambiguate.
 */
export const BADGE_COLORS = [
  "#7cb7e8",
  "#e58f9a",
  "#8fd1a8",
  "#c7a4f0",
  "#e8c26a",
  "#7fd0d0",
  "#f0a07a",
  "#b4c4d8",
] as const;

export function badgeColor(name: string | null | undefined): string {
  let h = 0;
  for (const ch of name ?? "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return BADGE_COLORS[h % BADGE_COLORS.length];
}

/**
 * Up to two letters for a team with no logo: the first letters of the first
 * and last words ("Los Angeles Lakers" -> "LL", not "LA", which two teams
 * would share). A one-word name gives its first two letters.
 */
export function teamInitials(name: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

export interface MatchupVisuals {
  home: TeamVisual | null;
  away: TeamVisual | null;
  homeAccent: string;
  awayAccent: string;
}

/**
 * Accents for one card, with the collision broken.
 *
 * Three teams share #002a5c upstream (Dallas, New England, Seattle) and two
 * share #000000 (Raiders, Steelers), so a head-to-head between any pair would
 * otherwise draw two identical bars — the accent would stop identifying
 * anything at exactly the moment it matters. The AWAY team yields to its
 * alternate, chosen because the home side is the one carrying the home
 * indicator and should keep its primary identity.
 */
export function matchupVisuals(
  homeName: string | null | undefined,
  awayName: string | null | undefined,
): MatchupVisuals {
  const home = teamVisual(homeName);
  const away = teamVisual(awayName);

  const homeAccent = home?.accent ?? "var(--neutral)";
  let awayAccent = away?.accent ?? "var(--neutral)";

  if (away && home && awayAccent === homeAccent) {
    awayAccent = away.alt;
  }

  return { home, away, homeAccent, awayAccent };
}

/** Substring match over full name and short name, for the search box. */
export function matchesTeamQuery(
  query: string,
  ...names: (string | null | undefined)[]
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return names.some((n) => {
    if (!n) return false;
    if (n.toLowerCase().includes(q)) return true;
    const v = teamVisual(n);
    return !!v && (v.short.toLowerCase().includes(q) || v.abbr.includes(q));
  });
}
