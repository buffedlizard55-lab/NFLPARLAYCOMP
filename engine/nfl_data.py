#!/usr/bin/env python3
"""
NFL metadata handling: schedule, injuries, venues, weather.

Uses only official/public free sources:
- ESPN keyless site API for scoreboard/schedule
- ESPN core venues API for coordinates
- NWS api.weather.gov for forecasts (forward-only)

All data stored verbatim with source URLs and SHA.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

from .utils import iso_now, make_flag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_NFL = os.path.join(ROOT, "data", "raw", "nfl")
RAW_NWS = os.path.join(ROOT, "data", "raw", "nws")

def load_schedule() -> Dict[str, Any]:
    path = os.path.join(RAW_NFL, "schedule.json")
    if not os.path.exists(path):
        return {"weeks": {}, "flags": [make_flag("MISSING_DATA", "NFL schedule not collected yet", severity="medium")]}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_injuries() -> Dict[str, Any]:
    path = os.path.join(RAW_NFL, "injuries.json")
    if not os.path.exists(path):
        return {"payload": {}, "flags": [make_flag("MISSING_DATA", "Injuries not collected", severity="low")]}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_venues() -> Dict[str, Any]:
    path = os.path.join(RAW_NFL, "venues.json")
    if not os.path.exists(path):
        return {"venues": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_weather() -> Dict[str, Any]:
    path = os.path.join(RAW_NWS, "forecasts.json")
    if not os.path.exists(path):
        return {"games": {}, "flags": [make_flag("WEATHER_UNAVAILABLE", "Weather forecasts not collected (forward-only)", severity="low")]}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_upcoming_games(schedule: Dict[str, Any] | None = None) -> List[dict]:
    schedule = schedule or load_schedule()
    upcoming = []
    for week, payload in (schedule.get("weeks") or {}).items():
        for game in payload.get("games", []):
            if game.get("status") != "STATUS_FINAL":
                upcoming.append({**game, "week": week})
    return upcoming

def get_team_from_event_ticker(event_ticker: str) -> tuple[str | None, str | None]:
    """Parse away/home from Kalshi event ticker like KXNFLGAME-26SEP20CLETB (CLE at TB)."""
    # Format: KXNFLxxx-YYMONDD<AWAY><HOME>
    # Last 4-6 chars are team abbreviations, e.g., CLETB -> away CLE, home TB
    # We need mapping of NFL abbreviations
    if not event_ticker or "-" not in event_ticker:
        return None, None
    parts = event_ticker.split("-")
    if len(parts) < 2:
        return None, None
    teams_part = parts[-1]
    # Remove date prefix: e.g., 26SEP20CLETB -> after 7 chars date, rest teams
    # Date is YYMONDD = 7 chars (26SEP20)
    if len(teams_part) <= 7:
        return None, None
    team_codes = teams_part[7:]
    # Team codes can be 2-3 letters each, need to split
    # Common NFL abbreviations: ARI, ATL, BAL, BUF, CAR, CHI, CIN, CLE, DAL, DEN, DET, GB, HOU, IND, JAX, KC, LAC, LAR, LV, MIA, MIN, NE, NO, NYG, NYJ, PHI, PIT, SF, SEA, TB, TEN, WAS
    # Try split by known abbreviations
    known = ["ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB","HOU","IND","JAX","KC","LAC","LAR","LV","MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT","SF","SEA","TB","TEN","WAS"]
    # Try to find two known abbrs that concatenate to team_codes
    for i in range(2, 5):
        away = team_codes[:i]
        home = team_codes[i:]
        if away in known and home in known:
            return away, home
    # Fallback: split half
    mid = len(team_codes)//2
    return team_codes[:mid], team_codes[mid:]

def enrich_market_with_nfl_context(market: dict, schedule: dict | None = None) -> dict:
    """Add home/away, venue, indoor flag from ESPN schedule."""
    event_ticker = market.get("event_ticker")
    away, home = get_team_from_event_ticker(event_ticker)
    enriched = {**market, "parsed_away": away, "parsed_home": home}
    if schedule:
        for week_payload in schedule.get("weeks", {}).values():
            for game in week_payload.get("games", []):
                if game.get("home") == home and game.get("away") == away:
                    enriched["espn_venue"] = game.get("venue")
                    enriched["espn_indoor"] = game.get("indoor")
                    enriched["espn_game_id"] = game.get("id")
                    enriched["espn_url"] = game.get("espn_url")
                    break
    return enriched
