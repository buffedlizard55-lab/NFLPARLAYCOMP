#!/usr/bin/env python3
"""Utility helpers: hashing, time, safe parsing, verification links."""
from __future__ import annotations

import hashlib
import json
import time
import datetime as dt
import re
from typing import Any

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return sha256_hex(raw)

def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def iso_from_epoch(ts: float | int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))

def parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None

def epoch_from_iso(s: str | None) -> int | None:
    d = parse_iso(s)
    return int(d.timestamp()) if d else None

def safe_float(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default

def safe_int(v: Any, default: int | None = None) -> int | None:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default

# Verification link builders (official sources only)

def kalshi_market_url(ticker: str) -> str:
    # Official Kalshi market page
    # Verified: https://kalshi.com/markets/<ticker> resolves, but trade API is canonical
    return f"https://kalshi.com/markets/{ticker}"

def kalshi_api_market_url(ticker: str) -> str:
    return f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"

def kalshi_api_event_url(event_ticker: str) -> str:
    return f"https://api.elections.kalshi.com/trade-api/v2/events/{event_ticker}"

def kalshi_series_url(series_ticker: str) -> str:
    return f"https://api.elections.kalshi.com/trade-api/v2/series/{series_ticker}"

def espn_game_url(game_id: str) -> str:
    return f"https://www.espn.com/nfl/game/_/gameId/{game_id}"

def nws_points_url(lat: str, lon: str) -> str:
    return f"https://api.weather.gov/points/{lat},{lon}"

# Slug parsing (verified pattern from collector)
SEASON_SLUG_RE = re.compile(
    r"^KXNFL[A-Z0-9]*-(26(?:SEP|OCT|NOV|DEC)|27(?:JAN|FEB))(\d{2})[A-Z0-9]{2,10}$"
)

MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}

def slug_date(event_ticker: str) -> dt.date | None:
    m = SEASON_SLUG_RE.match(event_ticker or "")
    if not m:
        return None
    mon, day = m.group(1)[-3:], int(m.group(2))
    year = 2026 if mon in ("SEP", "OCT", "NOV", "DEC") else 2027
    try:
        return dt.date(year, MONTHS[mon], day)
    except ValueError:
        return None

def implied_prob_from_price(price_cents: float) -> float:
    """Kalshi price is in dollars $0.01-$0.99 => implied prob 1%-99%"""
    return max(0.01, min(0.99, price_cents))

def price_to_cents(price_dollars: float | None) -> int | None:
    if price_dollars is None:
        return None
    try:
        return int(round(float(price_dollars) * 100))
    except:
        return None

# Flag types
FLAG_TYPES = {
    "MISSING_DATA",
    "UNVERIFIED_DATA",
    "SUSPICIOUS_PRICE",
    "MISSING_TIMESTAMP",
    "LIQUIDITY_PROBLEM",
    "IMPOSSIBLE_EXECUTION",
    "API_ERROR",
    "DUPLICATE_TRADE",
    "CALCULATION_ERROR",
    "SETTLEMENT_INCONSISTENCY",
    "DATA_SOURCE_CONFLICT",
    "WEATHER_UNAVAILABLE",
    "INJURY_UNAVAILABLE",
    "ORDERBOOK_MISSING",
    "CANDLE_MISSING",
    "COMBO_NOT_NATIVE",
    "SYNTHETIC_PARLAY",
}

def make_flag(flag_type: str, message: str, trade_id: str | None = None,
              market_ticker: str | None = None, severity: str = "medium") -> dict:
    assert flag_type in FLAG_TYPES, f"Unknown flag type {flag_type}"
    return {
        "flag_type": flag_type,
        "message": message,
        "trade_id": trade_id,
        "market_ticker": market_ticker,
        "severity": severity,
        "created_at": iso_now(),
    }
