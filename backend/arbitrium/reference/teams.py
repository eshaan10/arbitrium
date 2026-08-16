"""Canonical team registry.

Maps a source-specific team identity (Kalshi suffix code + custom_strike UUID)
to one canonical team. Built now for NFL because it is the live data source;
Phase 2's Odds API matching reuses this same registry (canonical `name` is the
cross-source join key), so it is foundational, not throwaway.

NFL UUIDs were collected from the live Kalshi API (custom_strike.football_team).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    """One canonical team plus the stable identifiers used to resolve it."""

    code: str  # Kalshi suffix code / standard abbreviation, e.g. 'KC'
    name: str  # canonical full name, e.g. 'Kansas City Chiefs' (cross-source key)
    kalshi_uuid: str  # custom_strike.football_team — stable Kalshi identifier
    league: str


_NFL_TEAMS: list[Team] = [
    Team("ARI", "Arizona Cardinals", "d73dae4f-1f08-4b5e-bf23-4e25e9b6a69c", "NFL"),
    Team("ATL", "Atlanta Falcons", "75685be6-4388-4bba-8bcb-d0b0c24feb50", "NFL"),
    Team("BAL", "Baltimore Ravens", "a69a57af-f1a1-4d44-ab62-e220ebaa2a5c", "NFL"),
    Team("BUF", "Buffalo Bills", "f9acd396-ba35-4cae-a431-a44b2af707b0", "NFL"),
    Team("CAR", "Carolina Panthers", "e37050ce-354f-4dd0-b2d8-0bd1e9650eb7", "NFL"),
    Team("CHI", "Chicago Bears", "9a77500a-1945-495e-b6f5-5c35bedaa8b9", "NFL"),
    Team("CIN", "Cincinnati Bengals", "b007a1ab-bca6-42c7-8706-62607a605866", "NFL"),
    Team("CLE", "Cleveland Browns", "05cc62a4-bd74-4b2c-ab7b-1b177b9f6790", "NFL"),
    Team("DAL", "Dallas Cowboys", "62b97b7c-5503-461c-b328-fd8543219b22", "NFL"),
    Team("DEN", "Denver Broncos", "0aa02fd7-1bb1-474b-98e1-5379d0a191e3", "NFL"),
    Team("DET", "Detroit Lions", "f95a55a7-8472-4ffa-be20-14547e3c32ff", "NFL"),
    Team("GB", "Green Bay Packers", "08c52d1f-7ce1-445f-be72-97de0554ecc8", "NFL"),
    Team("HOU", "Houston Texans", "96edbad3-1be5-4528-a3ed-c6e0c28c5fa0", "NFL"),
    Team("IND", "Indianapolis Colts", "fe5f8219-fef4-4498-83d5-f6cc6f2cb7bf", "NFL"),
    Team("JAC", "Jacksonville Jaguars", "61a75ab7-eaf0-4601-b920-86b1e165007d", "NFL"),
    Team("KC", "Kansas City Chiefs", "64f72720-2e4a-4cc8-a39b-ca148aecb389", "NFL"),
    Team("LAC", "Los Angeles Chargers", "611e3786-3bfe-4919-bbd5-bc70fc13d827", "NFL"),
    Team("LAR", "Los Angeles Rams", "422d5fd7-ad18-4c96-902d-6f7c50e4660f", "NFL"),
    Team("LV", "Las Vegas Raiders", "8b1ce23e-7d64-4213-85e9-7d12bc8c4d85", "NFL"),
    Team("MIA", "Miami Dolphins", "4cba614d-2d32-48ef-a066-1524437fbaff", "NFL"),
    Team("MIN", "Minnesota Vikings", "2279efa0-9284-4224-9647-09b14f6983ce", "NFL"),
    Team("NE", "New England Patriots", "d1d64188-5cd5-4feb-97ff-8542c9dbeb43", "NFL"),
    Team("NO", "New Orleans Saints", "f7c2cd06-61bf-469e-984f-3ef56cb8f3d7", "NFL"),
    Team("NYG", "New York Giants", "4fa3f3ec-f7e7-41ec-9383-a40af2d26297", "NFL"),
    Team("NYJ", "New York Jets", "ccc2af2d-5c4d-4717-8036-5ba6bec5cfbd", "NFL"),
    Team("PHI", "Philadelphia Eagles", "bc65405b-5bda-425c-b7c5-681c382e6a5a", "NFL"),
    Team("PIT", "Pittsburgh Steelers", "6aa76797-7833-45e1-85e3-96e0122801e1", "NFL"),
    Team("SEA", "Seattle Seahawks", "8e52cc75-cba8-4373-9b62-b535b53b3be8", "NFL"),
    Team("SF", "San Francisco 49ers", "bfaa7639-8bdf-47b2-8d28-98d2cdbefbcb", "NFL"),
    Team("TB", "Tampa Bay Buccaneers", "1105fa0d-c798-4020-9e24-f377a334b3d9", "NFL"),
    Team("TEN", "Tennessee Titans", "7c86629b-eafc-47b4-9204-b46a2d0e9cbb", "NFL"),
    Team("WAS", "Washington Commanders", "aa65dda6-9cb8-4c8b-812b-d0c1feaae54f", "NFL"),
]

# Aliases for cross-source name matching (Phase 2, The Odds API). Keys are
# NORMALISED alternate names -> canonical registry name. Seed with known
# historical/alternate labels; extend as real unmatched-name logs surface.
_NAME_ALIASES: dict[str, dict[str, str]] = {
    "NFL": {
        "washington football team": "Washington Commanders",
        "washington redskins": "Washington Commanders",
        "oakland raiders": "Las Vegas Raiders",
        "san diego chargers": "Los Angeles Chargers",
    },
}


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


# Registry indexed by (league, code). Extend with other leagues as they go live.
_REGISTRY: dict[str, dict[str, Team]] = {}
_UUID_INDEX: dict[str, dict[str, Team]] = {}
_NAME_INDEX: dict[str, dict[str, Team]] = {}
for _t in _NFL_TEAMS:
    _REGISTRY.setdefault(_t.league, {})[_t.code] = _t
    _UUID_INDEX.setdefault(_t.league, {})[_t.kalshi_uuid] = _t
    _NAME_INDEX.setdefault(_t.league, {})[_normalize_name(_t.name)] = _t


def resolve_team(league: str, code: str, kalshi_uuid: str | None = None) -> Team | None:
    """Resolve a team by suffix code within a league.

    If ``kalshi_uuid`` is supplied it is validated against the registry; a
    mismatch (Kalshi changed a UUID, or a code collision) is a signal worth
    surfacing, so the caller can log it. Returns None for unknown codes.
    """
    team = _REGISTRY.get(league, {}).get(code)
    if team is None:
        return None
    if kalshi_uuid and team.kalshi_uuid != kalshi_uuid:
        return None
    return team


def team_by_uuid(league: str, kalshi_uuid: str) -> Team | None:
    """Resolve a team by its stable Kalshi UUID (fallback when a code is ambiguous)."""
    return _UUID_INDEX.get(league, {}).get(kalshi_uuid)


def resolve_by_name(league: str, name: str) -> Team | None:
    """Resolve a team by full name (e.g. The Odds API's ``home_team``).

    Matches on the canonical name, then the alias map, both normalised
    (lower-cased, whitespace-collapsed). Returns None for anything unresolved —
    callers skip-and-log rather than guess, so a genuinely new/renamed team never
    gets silently mis-matched.
    """
    if not name:
        return None
    norm = _normalize_name(name)
    team = _NAME_INDEX.get(league, {}).get(norm)
    if team is not None:
        return team
    alias = _NAME_ALIASES.get(league, {}).get(norm)
    if alias is not None:
        return _NAME_INDEX.get(league, {}).get(_normalize_name(alias))
    return None
