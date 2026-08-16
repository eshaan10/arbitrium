"""Team registry resolution: code, UUID, and cross-source name matching."""

from __future__ import annotations

from arbitrium.reference.teams import resolve_by_name, resolve_team, team_by_uuid


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
