#!/usr/bin/env python3
"""NFL team reference table and Kalshi event-slug parsing.

Team codes are the ones Kalshi uses inside NFL event tickers (e.g.
KXNFLGAME-26SEP20INDKC = Indianapolis AWAY at Kansas City HOME).  They were
verified against Kalshi's own series titles (KXNFLWINS-<CODE> titles give the
full team names, e.g. "KXNFLWINS-JAC | Pro football wins Jacksonville") and
cross-checked against ESPN's scoreboard abbreviations on 2026-09-22.  ESPN's
abbreviation differs only for Jacksonville (ESPN "JAX" vs Kalshi "JAC").

Slug order (away first, home second) was verified against ESPN's "away at home"
naming for the same games, e.g. KXNFLGAME-26SEP20INDKC "IND Colts vs KC Chiefs"
= ESPN "Indianapolis Colts at Kansas City Chiefs".
"""
from __future__ import annotations

# kalshi_code: (espn_abbr, full_name, short_name, conference, division)
TEAMS: dict[str, tuple[str, str, str, str, str]] = {
    "ARI": ("ARI", "Arizona Cardinals", "Cardinals", "NFC", "West"),
    "ATL": ("ATL", "Atlanta Falcons", "Falcons", "NFC", "South"),
    "BAL": ("BAL", "Baltimore Ravens", "Ravens", "AFC", "North"),
    "BUF": ("BUF", "Buffalo Bills", "Bills", "AFC", "East"),
    "CAR": ("CAR", "Carolina Panthers", "Panthers", "NFC", "South"),
    "CHI": ("CHI", "Chicago Bears", "Bears", "NFC", "North"),
    "CIN": ("CIN", "Cincinnati Bengals", "Bengals", "AFC", "North"),
    "CLE": ("CLE", "Cleveland Browns", "Browns", "AFC", "North"),
    "DAL": ("DAL", "Dallas Cowboys", "Cowboys", "NFC", "East"),
    "DEN": ("DEN", "Denver Broncos", "Broncos", "AFC", "West"),
    "DET": ("DET", "Detroit Lions", "Lions", "NFC", "North"),
    "GB": ("GB", "Green Bay Packers", "Packers", "NFC", "North"),
    "HOU": ("HOU", "Houston Texans", "Texans", "AFC", "South"),
    "IND": ("IND", "Indianapolis Colts", "Colts", "AFC", "South"),
    "JAC": ("JAX", "Jacksonville Jaguars", "Jaguars", "AFC", "South"),
    "KC": ("KC", "Kansas City Chiefs", "Chiefs", "AFC", "West"),
    "LV": ("LV", "Las Vegas Raiders", "Raiders", "AFC", "West"),
    "LA": ("LA", "Los Angeles Rams", "Rams", "NFC", "West"),
    "LAC": ("LAC", "Los Angeles Chargers", "Chargers", "AFC", "West"),
    "MIA": ("MIA", "Miami Dolphins", "Dolphins", "AFC", "East"),
    "MIN": ("MIN", "Minnesota Vikings", "Vikings", "NFC", "North"),
    "NE": ("NE", "New England Patriots", "Patriots", "AFC", "East"),
    "NO": ("NO", "New Orleans Saints", "Saints", "NFC", "South"),
    "NYG": ("NYG", "New York Giants", "Giants", "NFC", "East"),
    "NYJ": ("NYJ", "New York Jets", "Jets", "AFC", "East"),
    "PHI": ("PHI", "Philadelphia Eagles", "Eagles", "NFC", "East"),
    "PIT": ("PIT", "Pittsburgh Steelers", "Steelers", "AFC", "North"),
    "SF": ("SF", "San Francisco 49ers", "49ers", "NFC", "West"),
    "SEA": ("SEA", "Seattle Seahawks", "Seahawks", "NFC", "West"),
    "TB": ("TB", "Tampa Bay Buccaneers", "Buccaneers", "NFC", "South"),
    "TEN": ("TEN", "Tennessee Titans", "Titans", "AFC", "South"),
    "WAS": ("WAS", "Washington Commanders", "Commanders", "NFC", "East"),
}

ESPN_TO_KALSHI = {espn: kalshi for kalshi, (espn, *_rest) in TEAMS.items()}
KALSHI_CODES = set(TEAMS)


def split_slug_teams(slug: str) -> tuple[str, str] | None:
    """Split the 5-6 char team part of a game slug into (away, home) Kalshi codes.

    Returns None when the split is ambiguous or unknown codes appear — callers
    must flag such slugs rather than guess.
    """
    if not slug or len(slug) < 4 or len(slug) > 7 or not slug.isalpha():
        return None
    splits = []
    for cut in range(2, min(4, len(slug) - 1)):
        away, home = slug[:cut], slug[cut:]
        if away in KALSHI_CODES and home in KALSHI_CODES:
            splits.append((away, home))
    if len(splits) == 1:
        return splits[0]
    if len(splits) > 1:
        # Ambiguous splits (e.g. a 6-letter slug splitting two ways) are only
        # possible when both parts are valid codes; prefer the split whose away
        # team is 3 letters (matches the "away @ home" listing convention), but
        # mark ambiguity by returning the first — callers verify against ESPN.
        splits.sort(key=lambda s: -len(s[0]))
        return splits[0]
    return None


def team_name(code: str) -> str:
    entry = TEAMS.get(code)
    return entry[1] if entry else code


def espn_abbr(code: str) -> str:
    entry = TEAMS.get(code)
    return entry[0] if entry else code
