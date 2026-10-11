"""Canonical team registry, keyed by league.

Maps each source's identity for a team to one canonical team:

  * Kalshi — market suffix code, validated against the ``custom_strike`` UUID;
  * The Odds API — full team name (``name`` IS the Odds API spelling, and is the
    cross-source join key stored in ``events.home_team`` / ``away_team``);
  * ESPN — ``team.id``, which is stable where ESPN's display names and
    abbreviations are not ("LA Clippers", GS, NO, NY, SA, UTAH, WSH).

Every lookup is scoped by league. Codes and ESPN ids collide across leagues
(ATL is both the Falcons and the Hawks; ESPN id 1 is both too), so an unscoped
lookup would silently cross sports. Adding MLB or NHL is one more team list plus
one ``KALSHI_STRIKE_KEYS`` entry.

Display names, short names, colours and logos are NOT here: the frontend
generates those from ESPN's team list (see frontend/scripts/generate-teams.mjs).

Kalshi UUIDs were collected from the live API: NFL from
custom_strike.football_team, NBA (2026-10-09, all 30 suffixes across the open
KXNBAGAME events) from custom_strike.basketball_team. ESPN ids are from ESPN's
public teams endpoint for each league.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    """One canonical team plus the stable identifiers used to resolve it."""

    code: str  # Kalshi suffix code, e.g. 'KC', 'NOP'
    name: str  # canonical full name = The Odds API spelling (cross-source key)
    kalshi_uuid: str  # custom_strike.<KALSHI_STRIKE_KEYS[league]>
    league: str
    espn_id: str  # ESPN team.id — unique within a league only


# Which custom_strike field carries the team UUID, per league. Kalshi names it
# by sport, so reading the NFL key for an NBA market returns nothing and the
# UUID cross-check silently never runs.
KALSHI_STRIKE_KEYS: dict[str, str] = {
    "NFL": "football_team",
    "NBA": "basketball_team",
}


_NFL_TEAMS: list[Team] = [
    Team("ARI", "Arizona Cardinals", "d73dae4f-1f08-4b5e-bf23-4e25e9b6a69c", "NFL", "22"),
    Team("ATL", "Atlanta Falcons", "75685be6-4388-4bba-8bcb-d0b0c24feb50", "NFL", "1"),
    Team("BAL", "Baltimore Ravens", "a69a57af-f1a1-4d44-ab62-e220ebaa2a5c", "NFL", "33"),
    Team("BUF", "Buffalo Bills", "f9acd396-ba35-4cae-a431-a44b2af707b0", "NFL", "2"),
    Team("CAR", "Carolina Panthers", "e37050ce-354f-4dd0-b2d8-0bd1e9650eb7", "NFL", "29"),
    Team("CHI", "Chicago Bears", "9a77500a-1945-495e-b6f5-5c35bedaa8b9", "NFL", "3"),
    Team("CIN", "Cincinnati Bengals", "b007a1ab-bca6-42c7-8706-62607a605866", "NFL", "4"),
    Team("CLE", "Cleveland Browns", "05cc62a4-bd74-4b2c-ab7b-1b177b9f6790", "NFL", "5"),
    Team("DAL", "Dallas Cowboys", "62b97b7c-5503-461c-b328-fd8543219b22", "NFL", "6"),
    Team("DEN", "Denver Broncos", "0aa02fd7-1bb1-474b-98e1-5379d0a191e3", "NFL", "7"),
    Team("DET", "Detroit Lions", "f95a55a7-8472-4ffa-be20-14547e3c32ff", "NFL", "8"),
    Team("GB", "Green Bay Packers", "08c52d1f-7ce1-445f-be72-97de0554ecc8", "NFL", "9"),
    Team("HOU", "Houston Texans", "96edbad3-1be5-4528-a3ed-c6e0c28c5fa0", "NFL", "34"),
    Team("IND", "Indianapolis Colts", "fe5f8219-fef4-4498-83d5-f6cc6f2cb7bf", "NFL", "11"),
    Team("JAC", "Jacksonville Jaguars", "61a75ab7-eaf0-4601-b920-86b1e165007d", "NFL", "30"),
    Team("KC", "Kansas City Chiefs", "64f72720-2e4a-4cc8-a39b-ca148aecb389", "NFL", "12"),
    Team("LAC", "Los Angeles Chargers", "611e3786-3bfe-4919-bbd5-bc70fc13d827", "NFL", "24"),
    Team("LAR", "Los Angeles Rams", "422d5fd7-ad18-4c96-902d-6f7c50e4660f", "NFL", "14"),
    Team("LV", "Las Vegas Raiders", "8b1ce23e-7d64-4213-85e9-7d12bc8c4d85", "NFL", "13"),
    Team("MIA", "Miami Dolphins", "4cba614d-2d32-48ef-a066-1524437fbaff", "NFL", "15"),
    Team("MIN", "Minnesota Vikings", "2279efa0-9284-4224-9647-09b14f6983ce", "NFL", "16"),
    Team("NE", "New England Patriots", "d1d64188-5cd5-4feb-97ff-8542c9dbeb43", "NFL", "17"),
    Team("NO", "New Orleans Saints", "f7c2cd06-61bf-469e-984f-3ef56cb8f3d7", "NFL", "18"),
    Team("NYG", "New York Giants", "4fa3f3ec-f7e7-41ec-9383-a40af2d26297", "NFL", "19"),
    Team("NYJ", "New York Jets", "ccc2af2d-5c4d-4717-8036-5ba6bec5cfbd", "NFL", "20"),
    Team("PHI", "Philadelphia Eagles", "bc65405b-5bda-425c-b7c5-681c382e6a5a", "NFL", "21"),
    Team("PIT", "Pittsburgh Steelers", "6aa76797-7833-45e1-85e3-96e0122801e1", "NFL", "23"),
    Team("SEA", "Seattle Seahawks", "8e52cc75-cba8-4373-9b62-b535b53b3be8", "NFL", "26"),
    Team("SF", "San Francisco 49ers", "bfaa7639-8bdf-47b2-8d28-98d2cdbefbcb", "NFL", "25"),
    Team("TB", "Tampa Bay Buccaneers", "1105fa0d-c798-4020-9e24-f377a334b3d9", "NFL", "27"),
    Team("TEN", "Tennessee Titans", "7c86629b-eafc-47b4-9204-b46a2d0e9cbb", "NFL", "10"),
    Team("WAS", "Washington Commanders", "aa65dda6-9cb8-4c8b-812b-d0c1feaae54f", "NFL", "28"),
]

_NBA_TEAMS: list[Team] = [
    Team("ATL", "Atlanta Hawks", "e0729403-9c95-4ee2-b5d4-f704d8322570", "NBA", "1"),
    Team("BKN", "Brooklyn Nets", "7cc1eb26-46ee-44b7-94ad-248ee3b0fbd3", "NBA", "17"),
    Team("BOS", "Boston Celtics", "6dd427f5-fa02-40ef-aa90-cfa73e0c539e", "NBA", "2"),
    Team("CHA", "Charlotte Hornets", "7c980c51-fa76-4571-b165-242b2a00f3a1", "NBA", "30"),
    Team("CHI", "Chicago Bulls", "65f0250b-455d-43d7-b7dc-7d321bdf9abc", "NBA", "4"),
    Team("CLE", "Cleveland Cavaliers", "90381a35-42a6-4975-851f-175418e4271a", "NBA", "5"),
    Team("DAL", "Dallas Mavericks", "36547ae6-f0fa-4d06-a6e5-5bfa64a217ed", "NBA", "6"),
    Team("DEN", "Denver Nuggets", "ba2cb6be-9827-46a8-8e6f-d8661307ba77", "NBA", "7"),
    Team("DET", "Detroit Pistons", "65569528-1888-40aa-9d62-2b0e8142a9b4", "NBA", "8"),
    Team("GSW", "Golden State Warriors", "502c629b-4da7-40fd-92ab-20cb55411c35", "NBA", "9"),
    Team("HOU", "Houston Rockets", "a8625e4b-4ae6-4062-a7c1-0b6e1f4ae211", "NBA", "10"),
    Team("IND", "Indiana Pacers", "d059bab2-9fb5-42dd-8038-5a12474300ce", "NBA", "11"),
    Team("LAC", "Los Angeles Clippers", "daca4413-0ea1-4db2-a815-f05c181ef0a6", "NBA", "12"),
    Team("LAL", "Los Angeles Lakers", "2ef4d31c-0b46-4f43-a403-f44d62489034", "NBA", "13"),
    Team("MEM", "Memphis Grizzlies", "1cfe70b8-4dfc-47dc-acca-b68d4a725972", "NBA", "29"),
    Team("MIA", "Miami Heat", "a17e4a68-2999-4f60-b67e-3e80aa9e198b", "NBA", "14"),
    Team("MIL", "Milwaukee Bucks", "5dc3fe01-79a4-4f2f-a953-d922ea4a6dd3", "NBA", "15"),
    Team("MIN", "Minnesota Timberwolves", "29e3c04e-fadb-4006-be20-cbb8c159ce0e", "NBA", "16"),
    Team("NOP", "New Orleans Pelicans", "d3c8c2ac-c4a0-4d67-8b16-53cb91118dfc", "NBA", "3"),
    Team("NYK", "New York Knicks", "67468ecc-b868-43a4-b9dc-751a52894bb0", "NBA", "18"),
    Team("OKC", "Oklahoma City Thunder", "a85f6eca-2f3b-4f61-83ab-8d049f59ce2c", "NBA", "25"),
    Team("ORL", "Orlando Magic", "00c3e69d-d9b9-4ac3-bf79-19707fe43637", "NBA", "19"),
    Team("PHI", "Philadelphia 76ers", "0554528d-586b-461f-827b-801cf93e8a8e", "NBA", "20"),
    Team("PHX", "Phoenix Suns", "ace11dff-c5d1-4ab9-9452-5312253659fd", "NBA", "21"),
    Team("POR", "Portland Trail Blazers", "2229b01e-68eb-46ad-adf4-71a9533c84fc", "NBA", "22"),
    Team("SAC", "Sacramento Kings", "ab9e2e9a-3243-41b6-a291-95f4d9c6edf7", "NBA", "23"),
    Team("SAS", "San Antonio Spurs", "ad36c3e8-4194-4e63-920f-7c50f46191a6", "NBA", "24"),
    Team("TOR", "Toronto Raptors", "96c447dd-2cdd-4c58-a151-ef0df87de981", "NBA", "28"),
    Team("UTA", "Utah Jazz", "6f60dfb1-fda1-423f-b76f-67e9d24b9644", "NBA", "26"),
    Team("WAS", "Washington Wizards", "0464e75c-8bc8-4f18-9ee2-577832b889d6", "NBA", "27"),
]

# Sport-keyed: league -> its teams. The one place a new league is registered.
TEAMS_BY_LEAGUE: dict[str, list[Team]] = {
    "NFL": _NFL_TEAMS,
    "NBA": _NBA_TEAMS,
}

# Aliases for cross-source name matching. Keys are NORMALISED alternate names ->
# canonical registry name. Extend as real unmatched-name logs surface.
_NAME_ALIASES: dict[str, dict[str, str]] = {
    "NFL": {
        "washington football team": "Washington Commanders",
        "washington redskins": "Washington Commanders",
        "oakland raiders": "Las Vegas Raiders",
        "san diego chargers": "Los Angeles Chargers",
    },
    "NBA": {
        # ESPN's displayName. ESPN results should resolve by team.id instead,
        # but a name path that fails for one team is the bug that ships.
        "la clippers": "Los Angeles Clippers",
    },
}


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


# Indexes, all league -> key -> Team.
_REGISTRY: dict[str, dict[str, Team]] = {}
_UUID_INDEX: dict[str, dict[str, Team]] = {}
_NAME_INDEX: dict[str, dict[str, Team]] = {}
_ESPN_INDEX: dict[str, dict[str, Team]] = {}
for _league, _teams in TEAMS_BY_LEAGUE.items():
    for _t in _teams:
        assert _t.league == _league, f"{_t.name} is filed under {_league}"
        _REGISTRY.setdefault(_league, {})[_t.code] = _t
        _UUID_INDEX.setdefault(_league, {})[_t.kalshi_uuid] = _t
        _NAME_INDEX.setdefault(_league, {})[_normalize_name(_t.name)] = _t
        _ESPN_INDEX.setdefault(_league, {})[_t.espn_id] = _t


def teams(league: str) -> list[Team]:
    """Every registered team in a league (empty for an unregistered league)."""
    return list(TEAMS_BY_LEAGUE.get(league, []))


def kalshi_strike_uuid(league: str, market: dict) -> str | None:
    """The team UUID from a Kalshi market's ``custom_strike``, for this league."""
    key = KALSHI_STRIKE_KEYS.get(league)
    if key is None:
        return None
    return (market.get("custom_strike") or {}).get(key)


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


def team_by_espn_id(league: str, espn_id: str | int | None) -> Team | None:
    """Resolve a team by ESPN ``team.id`` within a league.

    The preferred path for ESPN results: ids are stable, while ESPN's display
    names drift from everyone else's ("LA Clippers"). Accepts an int as well,
    since ESPN serves the id as a string but callers may have coerced it.
    """
    if espn_id is None or espn_id == "":
        return None
    return _ESPN_INDEX.get(league, {}).get(str(espn_id))


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
