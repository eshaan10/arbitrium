"""Team registry resolution: code, UUID, ESPN id, and cross-source name matching."""

from __future__ import annotations

from arbitrium.reference.teams import (
    KALSHI_STRIKE_KEYS,
    TEAMS_BY_LEAGUE,
    kalshi_strike_uuid,
    resolve_by_name,
    resolve_team,
    team_by_espn_id,
    team_by_uuid,
    teams,
)


def test_resolve_by_code_and_uuid_validation():
    assert resolve_team("NFL", "KC").name == "Kansas City Chiefs"
    assert resolve_team("NFL", "KC", "64f72720-2e4a-4cc8-a39b-ca148aecb389").name == "Kansas City Chiefs"
    assert resolve_team("NFL", "KC", "wrong-uuid") is None  # UUID mismatch
    assert resolve_team("NFL", "ZZZ") is None


def test_team_by_uuid():
    assert team_by_uuid("NFL", "0aa02fd7-1bb1-474b-98e1-5379d0a191e3").code == "DEN"


# --- #4 cross-source name matching + skip -----------------------------------


def test_resolve_by_name_exact():
    assert resolve_by_name("NFL", "Kansas City Chiefs").code == "KC"


def test_resolve_by_name_is_normalized():
    # Case / whitespace differences must not break matching.
    assert resolve_by_name("NFL", "  kansas   city   chiefs ").code == "KC"


def test_resolve_by_name_alias():
    assert resolve_by_name("NFL", "Washington Football Team").name == "Washington Commanders"
    assert resolve_by_name("NFL", "Oakland Raiders").name == "Las Vegas Raiders"


def test_resolve_by_name_unknown_returns_none():
    # A genuinely unknown/renamed team must resolve to None so callers skip-and-log
    # rather than mis-match.
    assert resolve_by_name("NFL", "London Monarchs") is None
    assert resolve_by_name("NFL", "") is None


# --- NBA, against the identities captured live on 2026-10-09 -----------------
#
# These three tables are what the sources ACTUALLY served, not what the registry
# says. A rename or a new suffix shows up here as a failing literal rather than
# as a week of silently skipped events.

# Every suffix in every KXNBAGAME event returning markets (44 open + 24 settled),
# with its custom_strike.basketball_team UUID.
LIVE_KALSHI_NBA = {
    "ATL": "e0729403-9c95-4ee2-b5d4-f704d8322570", "BKN": "7cc1eb26-46ee-44b7-94ad-248ee3b0fbd3",
    "BOS": "6dd427f5-fa02-40ef-aa90-cfa73e0c539e", "CHA": "7c980c51-fa76-4571-b165-242b2a00f3a1",
    "CHI": "65f0250b-455d-43d7-b7dc-7d321bdf9abc", "CLE": "90381a35-42a6-4975-851f-175418e4271a",
    "DAL": "36547ae6-f0fa-4d06-a6e5-5bfa64a217ed", "DEN": "ba2cb6be-9827-46a8-8e6f-d8661307ba77",
    "DET": "65569528-1888-40aa-9d62-2b0e8142a9b4", "GSW": "502c629b-4da7-40fd-92ab-20cb55411c35",
    "HOU": "a8625e4b-4ae6-4062-a7c1-0b6e1f4ae211", "IND": "d059bab2-9fb5-42dd-8038-5a12474300ce",
    "LAC": "daca4413-0ea1-4db2-a815-f05c181ef0a6", "LAL": "2ef4d31c-0b46-4f43-a403-f44d62489034",
    "MEM": "1cfe70b8-4dfc-47dc-acca-b68d4a725972", "MIA": "a17e4a68-2999-4f60-b67e-3e80aa9e198b",
    "MIL": "5dc3fe01-79a4-4f2f-a953-d922ea4a6dd3", "MIN": "29e3c04e-fadb-4006-be20-cbb8c159ce0e",
    "NOP": "d3c8c2ac-c4a0-4d67-8b16-53cb91118dfc", "NYK": "67468ecc-b868-43a4-b9dc-751a52894bb0",
    "OKC": "a85f6eca-2f3b-4f61-83ab-8d049f59ce2c", "ORL": "00c3e69d-d9b9-4ac3-bf79-19707fe43637",
    "PHI": "0554528d-586b-461f-827b-801cf93e8a8e", "PHX": "ace11dff-c5d1-4ab9-9452-5312253659fd",
    "POR": "2229b01e-68eb-46ad-adf4-71a9533c84fc", "SAC": "ab9e2e9a-3243-41b6-a291-95f4d9c6edf7",
    "SAS": "ad36c3e8-4194-4e63-920f-7c50f46191a6", "TOR": "96c447dd-2cdd-4c58-a151-ef0df87de981",
    "UTA": "6f60dfb1-fda1-423f-b76f-67e9d24b9644", "WAS": "0464e75c-8bc8-4f18-9ee2-577832b889d6",
}

# The Odds API basketball_nba /events response, spelled exactly as served.
LIVE_ODDS_API_NBA = [
    "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls",
    "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets", "Detroit Pistons",
    "Golden State Warriors", "Houston Rockets", "Indiana Pacers", "Los Angeles Clippers",
    "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat", "Milwaukee Bucks",
    "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks", "Oklahoma City Thunder",
    "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns", "Portland Trail Blazers",
    "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz", "Washington Wizards",
]

# ESPN's NBA teams endpoint: team.id -> (abbreviation, displayName). Note the six
# abbreviations that differ from Kalshi's, and "LA Clippers".
LIVE_ESPN_NBA = {
    "1": ("ATL", "Atlanta Hawks"), "2": ("BOS", "Boston Celtics"), "17": ("BKN", "Brooklyn Nets"),
    "30": ("CHA", "Charlotte Hornets"), "4": ("CHI", "Chicago Bulls"),
    "5": ("CLE", "Cleveland Cavaliers"), "6": ("DAL", "Dallas Mavericks"),
    "7": ("DEN", "Denver Nuggets"), "8": ("DET", "Detroit Pistons"),
    "9": ("GS", "Golden State Warriors"), "10": ("HOU", "Houston Rockets"),
    "11": ("IND", "Indiana Pacers"), "12": ("LAC", "LA Clippers"),
    "13": ("LAL", "Los Angeles Lakers"), "29": ("MEM", "Memphis Grizzlies"),
    "14": ("MIA", "Miami Heat"), "15": ("MIL", "Milwaukee Bucks"),
    "16": ("MIN", "Minnesota Timberwolves"), "3": ("NO", "New Orleans Pelicans"),
    "18": ("NY", "New York Knicks"), "25": ("OKC", "Oklahoma City Thunder"),
    "19": ("ORL", "Orlando Magic"), "20": ("PHI", "Philadelphia 76ers"),
    "21": ("PHX", "Phoenix Suns"), "22": ("POR", "Portland Trail Blazers"),
    "23": ("SAC", "Sacramento Kings"), "24": ("SA", "San Antonio Spurs"),
    "28": ("TOR", "Toronto Raptors"), "26": ("UTAH", "Utah Jazz"),
    "27": ("WSH", "Washington Wizards"),
}

# ESPN's NFL teams endpoint: team.id -> displayName.
LIVE_ESPN_NFL = {
    "22": "Arizona Cardinals", "1": "Atlanta Falcons", "33": "Baltimore Ravens",
    "2": "Buffalo Bills", "29": "Carolina Panthers", "3": "Chicago Bears",
    "4": "Cincinnati Bengals", "5": "Cleveland Browns", "6": "Dallas Cowboys",
    "7": "Denver Broncos", "8": "Detroit Lions", "9": "Green Bay Packers",
    "34": "Houston Texans", "11": "Indianapolis Colts", "30": "Jacksonville Jaguars",
    "12": "Kansas City Chiefs", "13": "Las Vegas Raiders", "24": "Los Angeles Chargers",
    "14": "Los Angeles Rams", "15": "Miami Dolphins", "16": "Minnesota Vikings",
    "17": "New England Patriots", "18": "New Orleans Saints", "19": "New York Giants",
    "20": "New York Jets", "21": "Philadelphia Eagles", "23": "Pittsburgh Steelers",
    "25": "San Francisco 49ers", "26": "Seattle Seahawks", "27": "Tampa Bay Buccaneers",
    "10": "Tennessee Titans", "28": "Washington Commanders",
}


def test_nba_registry_has_30_teams():
    assert len(teams("NBA")) == 30


def test_every_league_has_unique_identifiers():
    for league, roster in TEAMS_BY_LEAGUE.items():
        for field in ("code", "name", "kalshi_uuid", "espn_id"):
            values = [getattr(t, field) for t in roster]
            dupes = {v for v in values if values.count(v) > 1}
            assert not dupes, f"{league} has duplicate {field}: {dupes}"


def test_every_live_kalshi_nba_suffix_resolves_with_its_uuid():
    for code, uuid in LIVE_KALSHI_NBA.items():
        team = resolve_team("NBA", code, uuid)
        assert team is not None, f"Kalshi suffix {code} did not resolve"
        assert team_by_uuid("NBA", uuid) is team
    # The registry holds nothing Kalshi doesn't serve, either.
    assert {t.code for t in teams("NBA")} == set(LIVE_KALSHI_NBA)


def test_every_live_odds_api_nba_name_resolves():
    for name in LIVE_ODDS_API_NBA:
        assert resolve_by_name("NBA", name) is not None, f"Odds API name {name!r} did not resolve"
    assert {t.name for t in teams("NBA")} == set(LIVE_ODDS_API_NBA)


def test_every_espn_id_resolves_and_agrees_with_the_name_path():
    for espn_id, (_abbr, display) in LIVE_ESPN_NBA.items():
        by_id = team_by_espn_id("NBA", espn_id)
        assert by_id is not None, f"ESPN NBA id {espn_id} did not resolve"
        assert resolve_by_name("NBA", display) is by_id  # incl. "LA Clippers"
    for espn_id, display in LIVE_ESPN_NFL.items():
        by_id = team_by_espn_id("NFL", espn_id)
        assert by_id is not None and by_id.name == display


def test_espn_lookup_is_scoped_by_league():
    # ESPN id 1 is a different team in each league; so are shared codes.
    assert team_by_espn_id("NFL", "1").name == "Atlanta Falcons"
    assert team_by_espn_id("NBA", "1").name == "Atlanta Hawks"
    assert team_by_espn_id("NBA", 1).name == "Atlanta Hawks"  # int-coerced id
    assert resolve_team("NFL", "DAL").name == "Dallas Cowboys"
    assert resolve_team("NBA", "DAL").name == "Dallas Mavericks"
    assert team_by_espn_id("NBA", "99") is None
    assert team_by_espn_id("NBA", None) is None
    assert team_by_espn_id("MLB", "1") is None


def test_no_canonical_name_is_shared_across_leagues():
    """events.home_team stores the bare name, and some readers (team follow,
    favourites) key on it — a cross-league collision would merge two teams."""
    seen: dict[str, str] = {}
    for league, roster in TEAMS_BY_LEAGUE.items():
        for t in roster:
            assert t.name not in seen, f"{t.name!r} is in both {seen[t.name]} and {league}"
            seen[t.name] = league


def test_kalshi_strike_key_is_per_league():
    assert KALSHI_STRIKE_KEYS == {"NFL": "football_team", "NBA": "basketball_team"}
    market = {"custom_strike": {"basketball_team": LIVE_KALSHI_NBA["BOS"]}}
    assert kalshi_strike_uuid("NBA", market) == LIVE_KALSHI_NBA["BOS"]
    # Reading NFL's key off an NBA market finds nothing — the bug this replaces.
    assert kalshi_strike_uuid("NFL", market) is None
    assert kalshi_strike_uuid("NBA", {}) is None
