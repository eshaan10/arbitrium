import { TEAM_VISUALS, type TeamVisual } from "./teams.generated";

export type { TeamVisual };

/** Logos are vendored under public/, not fetched from a third party at runtime. */
export function logoPath(visual: TeamVisual): string {
  return `/logos/nfl/${visual.abbr}.png`;
}

export function teamVisual(name: string | null | undefined): TeamVisual | null {
  if (!name) return null;
  return TEAM_VISUALS[name] ?? null;
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
