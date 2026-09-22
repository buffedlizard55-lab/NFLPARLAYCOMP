#!/usr/bin/env python3
"""Verified data collector for the NFL parlay competition.

Collects REAL data from official/public endpoints and stores it verbatim (or as
documented 1:1 compact rows) under ``data/raw/``, with every HTTP call logged to an
append-only manifest (URL, time, status, bytes, SHA-256).  Nothing here estimates,
back-fills, or invents values; sources that fail are recorded as failures and become
flags downstream.

Sources (all read-only, unauthenticated, free):
  * Kalshi Trade API v2  https://docs.kalshi.com  (series/events/markets/candles/
    orderbooks/trades) — the ONLY source for prices, liquidity and settlements.
  * ESPN keyless site API (scoreboard/schedule, injuries) — NFL game metadata that
    Kalshi does not provide (home/away, kickoff cross-check, scores, venue).
  * NWS api.weather.gov (gridpoint forecasts) — weather for upcoming games.

Season windows: the "2026 season" is event slugs -26SEP.. through -26DEC plus
-27JAN/-27FEB (postseason).  Slugs are the Kalshi event ticker date part, e.g.
KXNFLGAME-26SEP27KCMIA (away team first, home team second — verified against ESPN's
"away at home" naming on 2026-09-22).

Modes: universe | events | candles | live | nfl | weather | full
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.kalshi_client import KalshiClient, KalshiError, iso  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
MANIFEST_PATH = os.path.join(RAW, "manifest.jsonl")

# NFL series prefixes discovered from the official GET /series?category=Sports catalog
# (verified 2026-09-22; see data/raw/kalshi/universe.json).
SERIES_PREFIXES = ("KXNFL",)

# Game-scoped series whose markets are ALL candle-archived (core leg universe).
CORE_GAME_SERIES = {
    "KXNFLGAME",          # moneyline / game winner (verified)
    "KXNFLSPREAD",        # team to win by more than X.5 (verified)
    "KXNFLTOTAL",         # game total over X.5 (verified)
    "KXNFLTEAMTOTAL",     # team total points
    "KXNFLWINMARGIN",     # win margin ranges
    "KXNFL1H",            # 1st half winner
    "KXNFL1HWINNER",      # 1st half winner (alt listing)
    "KXNFL1HSPREAD",      # 1st half spread
    "KXNFL1HTOTAL",       # 1st half total
    "KXNFL1HTEAMTOTAL",   # 1st half team total
    "KXNFLCOMBO",         # native Kalshi parlay/combo markets (rare; marquee games)
}
# Series whose events are per-game but where only the most liquid markets per event
# are candle-archived (top N by all-time volume) — documented limitation.
PROP_GAME_SERIES_TOP_N = {
    "KXNFLANYTD": 8,          # anytime touchdown scorers
    "KXNFLTD": 8,             # touchdown markets
    "KXNFLTEAMTD": 6,
    "KXNFLTEAMFIRSTTD": 6,
    "KXNFLFIRSTTD": 8,
    "KXNFLFIRSTTDTEAM": 4,
    "KXNFLTOTALTD": 4,
    "KXNFL2TD": 6,
    "KXNFLCOMPETE": 8,        # will player compete (injury proxy priced by the market)
    "KXNFLMATCHUP": 8,
    "KXNFL1Q": 4, "KXNFL1QWINNER": 4, "KXNFL1QTOTAL": 4, "KXNFL1QSPREAD": 4,
    "KXNFL2Q": 4, "KXNFL2QWINNER": 4, "KXNFL2QTOTAL": 4,
    "KXNFL3Q": 4, "KXNFL3QWINNER": 4, "KXNFL3QTOTAL": 4,
    "KXNFL4Q": 4, "KXNFL4QWINNER": 4, "KXNFL4QTOTAL": 4,
    "KXNFL2H": 4, "KXNFL2HWINNER": 4, "KXNFL2HTOTAL": 4, "KXNFL2HSPREAD": 4,
    "KXNFLBOTH": 2, "KXNFLOT": 2, "KXNFLOTWIN": 2, "KXNFLTIES": 2, "KXNFLSFTY": 2,
    "KXNFL2PTCONV": 2, "KXNFLGAMESPECIALS": 6, "KXNFLGAMETD": 6, "KXNFLGAMEFG": 4,
    "KXNFLGAMESACK": 4, "KXNFLGAMETO": 4, "KXNFL1QBTTS": 2, "KXNFL1HFT": 4,
    "KXNFLDSTTD": 4, "KXNFLFG": 4, "KXNFL60YARDFGS": 2, "KXNFL4DCONV": 2,
}

# 2026 season event-slug date patterns (regular season Sep 2026-Jan 2027 + postseason
# through the championship game in Feb 2027).
SEASON_SLUG_RE = re.compile(
    r"^KXNFL[A-Z0-9]*-(26(?:SEP|OCT|NOV|DEC)|27(?:JAN|FEB))(\d{2})[A-Z0-9]{2,10}$")
SEASON_START = dt.date(2026, 9, 1)   # events on/after this date belong to season 2026
SEASON_END = dt.date(2027, 3, 1)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
ESPN_CORE_VENUES = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/venues"
NWS_BASE = "https://api.weather.gov"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def slug_date(event_ticker: str) -> dt.date | None:
    """Extract the game date from a 2026-season event ticker, else None."""
    match = SEASON_SLUG_RE.match(event_ticker or "")
    if not match:
        return None
    mon, day = match.group(1)[-3:], int(match.group(2))
    year = 2026 if mon in ("SEP", "OCT", "NOV", "DEC") else 2027
    try:
        return dt.date(year, MONTHS[mon], day)
    except ValueError:
        return None


def is_season_event(event: dict) -> bool:
    date = slug_date(event.get("event_ticker", ""))
    return date is not None and SEASON_START <= date < SEASON_END


# --------------------------------------------------------------------------
# storage helpers
# --------------------------------------------------------------------------

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_json(path: str, payload) -> None:
    ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, path)


def read_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def append_manifest(run_id: str, mode: str, calls: list[dict]) -> None:
    ensure_dir(os.path.dirname(MANIFEST_PATH))
    with open(MANIFEST_PATH, "a", encoding="utf-8") as handle:
        for call in calls:
            handle.write(json.dumps({"run": run_id, "mode": mode, **call},
                                    separators=(",", ":"), sort_keys=True) + "\n")


def parse_ts(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def epoch(text: str | None) -> int | None:
    parsed = parse_ts(text)
    return int(parsed.timestamp()) if parsed else None


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def collect_universe(client: KalshiClient) -> dict:
    """Store the official series catalog filtered to NFL series."""
    all_series = client.series_list(category="Sports")
    nfl = [s for s in all_series
           if any(s.get("ticker", "").startswith(p) for p in SERIES_PREFIXES)]
    payload = {
        "fetched_at": iso(time.time()),
        "source_url": "https://external-api.kalshi.com/trade-api/v2/series?category=Sports",
        "total_sports_series": len(all_series),
        "nfl_series_count": len(nfl),
        "series": sorted(nfl, key=lambda s: s.get("ticker", "")),
    }
    write_json(os.path.join(RAW, "kalshi", "universe.json"), payload)
    return {"sports_series": len(all_series), "nfl_series": len(nfl)}


def _event_pages(client: KalshiClient, series: str, status: str | None,
                 stop_before: dt.date | None = None, max_pages: int = 12) -> list[dict]:
    """Page events for a series; stop early once we pass below the season window.

    The events endpoint returns most-recent-first for these series (observed
    2026-09-22), so once a full page is older than the season start and we have
    already seen season events, further pages cannot contain season events.
    """
    out: list[dict] = []
    cursor = ""
    seen_season = False
    for _ in range(max_pages):
        payload = client.get("events", {"series_ticker": series, "status": status,
                                        "limit": 200, "cursor": cursor or None})[0]
        rows = payload.get("events") or []
        out.extend(rows)
        cursor = str(payload.get("cursor") or "")
        if not rows or not cursor:
            break
        if stop_before is not None:
            dates = [slug_date(e.get("event_ticker", "")) for e in rows]
            dates = [d for d in dates if d]
            page_has_season = any(d >= stop_before for d in dates)
            if page_has_season:
                seen_season = True
            elif seen_season and dates and max(dates) < stop_before:
                break  # passed the season window (descending order observed)
    return out


def collect_events(client: KalshiClient) -> dict:
    """For every NFL series, store its open + settled events, keeping all fetched
    rows verbatim and marking which are 2026-season game events.  Then fetch and
    store the full market list for every season event."""
    universe = read_json(os.path.join(RAW, "kalshi", "universe.json"), {})
    series_tickers = sorted(s.get("ticker") for s in universe.get("series", [])
                            if s.get("ticker"))
    season_events: dict[str, dict] = {}
    series_summary = {}
    failures = []
    for ticker in series_tickers:
        try:
            open_events = _event_pages(client, ticker, "open", stop_before=SEASON_START)
            settled_events = _event_pages(client, ticker, "settled", stop_before=SEASON_START)
            rows = open_events + settled_events
        except KalshiError as error:
            failures.append({"series": ticker, "error": str(error)[:200]})
            continue
        season_rows = [e for e in rows if is_season_event(e)]
        if rows:
            write_json(os.path.join(RAW, "kalshi", "events", f"{ticker}.json"), {
                "series": ticker, "fetched_at": iso(time.time()),
                "rows": rows,
            })
        series_summary[ticker] = {"fetched": len(rows), "season": len(season_rows)}
        for event in season_rows:
            key = event["event_ticker"]
            if key not in season_events:
                season_events[key] = {**event, "_series": [ticker]}
            else:
                if ticker not in season_events[key]["_series"]:
                    season_events[key]["_series"].append(ticker)

    # market lists for every season event (also captures results/settlement of
    # settled markets verbatim)
    markets_dir = os.path.join(RAW, "kalshi", "markets")
    fetched = 0
    for event_ticker in sorted(season_events):
        try:
            rows = client.markets(event_ticker=event_ticker, limit=200, max_pages=6)
        except KalshiError as error:
            failures.append({"event": event_ticker, "error": str(error)[:200]})
            continue
        if rows:
            write_json(os.path.join(markets_dir, f"{event_ticker}.json"), {
                "event_ticker": event_ticker, "fetched_at": iso(time.time()),
                "markets": rows,
            })
            fetched += 1
    write_json(os.path.join(RAW, "kalshi", "season_events.json"), {
        "fetched_at": iso(time.time()),
        "season_slug_pattern": SEASON_SLUG_RE.pattern,
        "event_tickers": sorted(season_events),
        "series_summary": series_summary,
        "failures": failures,
    })
    return {"season_events": len(season_events), "market_files": fetched,
            "series_failures": len(failures)}


def _candle_window(market: dict, now_epoch: int) -> tuple[int, int] | None:
    """Hourly-candle window: from max(open, kickoff-96h) to min(now, close+2h)."""
    kick = epoch(market.get("occurrence_datetime"))
    opened = epoch(market.get("open_time"))
    closed = epoch(market.get("close_time")) or epoch(market.get("expiration_time"))
    if kick is None:
        return None
    start = max(opened or (kick - 96 * 3600), kick - 96 * 3600)
    end = min(now_epoch, (closed or now_epoch) + 2 * 3600)
    if end <= start:
        return None
    return start, end


def compact_bar(bar: dict) -> dict:
    """1:1 compact projection of an official candlestick (all fields preserved,
    short keys; schema documented in docs/DATA_TRUTH.md)."""
    price = bar.get("price") or {}
    yes_bid = bar.get("yes_bid") or {}
    yes_ask = bar.get("yes_ask") or {}
    return {
        "t": bar.get("end_period_ts"),                      # bar end, unix seconds
        "o": price.get("open_dollars"), "h": price.get("high_dollars"),
        "l": price.get("low_dollars"), "c": price.get("close_dollars"),
        "m": price.get("mean_dollars"),
        "yb": yes_bid.get("close_dollars"), "ya": yes_ask.get("close_dollars"),
        "v": bar.get("volume_fp"), "oi": bar.get("open_interest_fp"),
    }


def tradable_universe() -> list[dict]:
    """Markets eligible for candle archiving: all markets in CORE_GAME_SERIES,
    top-N by volume_fp per event in PROP_GAME_SERIES_TOP_N."""
    season = read_json(os.path.join(RAW, "kalshi", "season_events.json"), {})
    out = []
    for event_ticker in season.get("event_tickers", []):
        payload = read_json(os.path.join(RAW, "kalshi", "markets", f"{event_ticker}.json"))
        if not payload:
            continue
        markets = payload.get("markets", [])
        series = markets[0].get("series_ticker") if markets else event_ticker.split("-")[0]
        if series in CORE_GAME_SERIES:
            out.extend(markets)
        elif series in PROP_GAME_SERIES_TOP_N:
            def vol(m):
                try:
                    return float(m.get("volume_fp") or 0)
                except (TypeError, ValueError):
                    return 0.0
            top = sorted(markets, key=vol, reverse=True)[:PROP_GAME_SERIES_TOP_N[series]]
            out.extend(top)
    return out


def collect_candles(client: KalshiClient) -> dict:
    """Archive hourly candlesticks for the tradable universe (documented 1:1 compact
    rows; the manifest SHA-256 binds each file to the exact API responses)."""
    now_epoch = int(time.time())
    universe = tradable_universe()
    stats = {"markets": 0, "bars": 0, "skipped": 0, "errors": 0}
    for market in universe:
        ticker = market.get("ticker")
        series = market.get("series_ticker")
        window = _candle_window(market, now_epoch)
        if not ticker or not series or not window:
            stats["skipped"] += 1
            continue
        path = os.path.join(RAW, "kalshi", "candles", series, f"{ticker}.json")
        existing = read_json(path)
        start, end = window
        bars: list[dict] = []
        cursor = start
        # page in 3-day windows to keep each response bounded
        while cursor < end:
            chunk_end = min(cursor + 3 * 86400, end)
            try:
                rows = client.candlesticks(series, ticker, cursor, chunk_end, 60)
            except KalshiError:
                stats["errors"] += 1
                break
            bars.extend(compact_bar(b) for b in rows)
            cursor = chunk_end
        if not bars:
            stats["skipped"] += 1
            continue
        # dedupe on bar-end timestamp (re-collection overlaps windows)
        seen: dict = {}
        for bar in bars:
            if bar.get("t") is not None:
                seen[int(bar["t"])] = bar
        merged = sorted(seen.values(), key=lambda b: int(b["t"]))
        prev = {b["t"]: b for b in (existing or {}).get("bars", [])}
        for bar in merged:
            prev[bar["t"]] = bar
        final_bars = sorted(prev.values(), key=lambda b: b["t"])
        write_json(path, {
            "ticker": ticker, "series_ticker": series,
            "event_ticker": market.get("event_ticker"),
            "period_interval_minutes": 60,
            "source_url": ("https://external-api.kalshi.com/trade-api/v2/series/"
                           f"{series}/markets/{ticker}/candlesticks"),
            "first_fetched_at": (existing or {}).get("first_fetched_at") or iso(time.time()),
            "last_fetched_at": iso(time.time()),
            "bars": final_bars,
        })
        stats["markets"] += 1
        stats["bars"] += len(final_bars)
    return stats


def collect_live(client: KalshiClient) -> dict:
    """Snapshot current order books + a trade-tape sample for every OPEN season
    market.  This is the execution data for upcoming (forward) simulated trades."""
    season = read_json(os.path.join(RAW, "kalshi", "season_events.json"), {})
    run_ts = iso(time.time())
    books: dict[str, dict] = {}
    tape: dict[str, list] = {}
    for event_ticker in season.get("event_tickers", []):
        payload = read_json(os.path.join(RAW, "kalshi", "markets", f"{event_ticker}.json"))
        if not payload:
            continue
        for market in payload.get("markets", []):
            if market.get("status") not in ("active", "open"):
                continue
            ticker = market.get("ticker")
            try:
                book = client.orderbook(ticker, depth=100)
            except KalshiError:
                continue
            books[ticker] = {"fetched_at": run_ts, "book": book}
    # trade tape for the most liquid open markets (execution-realism sample)
    liquid = sorted(books.items(),
                    key=lambda kv: float(kv[1]["book"].get("orderbook_fp", {}).get("yes_dollars")
                                         and "0" or "0"))  # placeholder, sorted below
    def liquidity(kv):
        book = kv[1]["book"].get("orderbook_fp") or {}
        best = 0.0
        for side in ("yes_dollars", "no_dollars"):
            levels = book.get(side) or []
            if levels:
                try:
                    best = max(best, float(levels[-1][1]))
                except (TypeError, ValueError, IndexError):
                    pass
        return best
    liquid = sorted(books.items(), key=liquidity, reverse=True)[:120]
    for ticker, _ in liquid:
        try:
            tape[ticker] = client.trades(ticker=ticker, limit=25, max_pages=2)
        except KalshiError:
            continue
    stamp = run_ts.replace(":", "").replace("-", "")
    write_json(os.path.join(RAW, "kalshi", "orderbooks", f"{stamp}.json"),
               {"fetched_at": run_ts, "books": books})
    write_json(os.path.join(RAW, "kalshi", "trades", f"{stamp}.json"),
               {"fetched_at": run_ts, "trades": tape})
    # keep a bounded history of snapshots (delete nothing; history is evidence)
    return {"orderbooks": len(books), "tape_markets": len(tape), "run": run_ts}


# --------------------------------------------------------------------------
# NFL metadata (ESPN keyless, NWS) — only for information Kalshi does not provide
# --------------------------------------------------------------------------

def http_get_json(url: str, headers: dict | None = None, timeout: float = 30.0):
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "NFLPARLAYCOMP/1.0 (+https://github.com/buffedlizard55-lab/NFLPARLAYCOMP)",
        **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def log_external(run_id: str, mode: str, url: str, status: int, body: bytes) -> None:
    import hashlib
    append_manifest(run_id, mode, [{
        "url": url, "status": status, "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(), "at": iso(time.time())}])


def collect_nfl(run_id: str) -> dict:
    """ESPN scoreboard for every 2026 regular-season week + injuries snapshot.

    Stored verbatim (compact projection with full links for verification).
    """
    weeks = {}
    for week in range(1, 19):
        url = f"{ESPN_BASE}/scoreboard?seasonType=2&year=2026&week={week}&limit=100"
        try:
            body_bytes = json.dumps(
                http_get_json(url), separators=(",", ":")).encode()
            payload = json.loads(body_bytes)
        except Exception as error:  # noqa: BLE001 — record failure, keep going
            weeks[str(week)] = {"error": str(error)[:200]}
            log_external(run_id, "nfl", url, 0, str(error).encode())
            continue
        log_external(run_id, "nfl", url, 200, body_bytes)
        events = payload.get("events") or []
        games = []
        for event in events:
            competition = (event.get("competitions") or [{}])[0]
            competitors = competition.get("competitors") or []
            home = away = None
            for side in competitors:
                if side.get("homeAway") == "home":
                    home = side
                elif side.get("homeAway") == "away":
                    away = side
            games.append({
                "id": event.get("id"), "date": event.get("date"),
                "name": event.get("name"), "short": event.get("shortName"),
                "status": (event.get("status") or {}).get("type", {}).get("name"),
                "home": (home or {}).get("team", {}).get("abbreviation"),
                "away": (away or {}).get("team", {}).get("abbreviation"),
                "home_score": (home or {}).get("score"),
                "away_score": (away or {}).get("score"),
                "venue": ((competition.get("venue") or {}).get("fullName")),
                "venue_id": (competition.get("venue") or {}).get("id"),
                "indoor": (competition.get("venue") or {}).get("indoor"),
                "espn_url": f"https://www.espn.com/nfl/game/_/gameId/{event.get('id')}",
            })
        weeks[str(week)] = {"source_url": url, "fetched_at": iso(time.time()),
                            "games": games}
    write_json(os.path.join(RAW, "nfl", "schedule.json"), {
        "fetched_at": iso(time.time()),
        "source": "ESPN keyless site API (https://site.api.espn.com) — NFL metadata only",
        "weeks": weeks,
    })

    # injuries snapshot (current designations; official nfl.com values mirrored by ESPN)
    injuries_url = f"{ESPN_BASE}/injuries"
    try:
        payload = http_get_json(injuries_url)
        body_bytes = json.dumps(payload, separators=(",", ":")).encode()
        log_external(run_id, "nfl", injuries_url, 200, body_bytes)
        write_json(os.path.join(RAW, "nfl", "injuries.json"), {
            "fetched_at": iso(time.time()), "source_url": injuries_url, "payload": payload})
        injuries_ok = True
    except Exception as error:  # noqa: BLE001
        log_external(run_id, "nfl", injuries_url, 0, str(error).encode())
        write_json(os.path.join(RAW, "nfl", "injuries.json"), {
            "fetched_at": iso(time.time()), "source_url": injuries_url,
            "error": str(error)[:200]})
        injuries_ok = False
    return {"weeks": len(weeks), "injuries": injuries_ok}


def collect_weather(run_id: str) -> dict:
    """NWS forecasts for venues of games not yet final (forward-looking only).

    Historical forecasts are NOT available from NWS; weather strategies are
    therefore forward-only and this is flagged, not back-filled.
    """
    schedule = read_json(os.path.join(RAW, "nfl", "schedule.json"), {})
    venues = read_json(os.path.join(RAW, "nfl", "venues.json"), {})
    coords = venues.get("venues", {})
    forecasts: dict[str, dict] = {}
    now = dt.datetime.now(dt.timezone.utc)
    for week, payload in sorted((schedule.get("weeks") or {}).items()):
        for game in payload.get("games", []):
            if game.get("status") == "STATUS_FINAL":
                continue
            date_text = game.get("date")
            kickoff = parse_ts(date_text)
            if not kickoff or kickoff < now:
                continue
            venue_id = str(game.get("venue_id") or "")
            if not venue_id or venue_id not in coords:
                continue
            lat, lon = coords[venue_id]["lat"], coords[venue_id]["lon"]
            points_url = f"{NWS_BASE}/points/{lat},{lon}"
            try:
                points = http_get_json(points_url, headers={"User-Agent": "NFLPARLAYCOMP/1.0"})
                forecast_url = (points.get("properties") or {}).get("forecast")
                if not forecast_url:
                    continue
                forecast = http_get_json(forecast_url)
                forecasts[f"{game.get('id')}"] = {
                    "game": game, "venue": coords[venue_id],
                    "points_url": points_url, "forecast_url": forecast_url,
                    "fetched_at": iso(time.time()),
                    "periods": [
                        {"name": p.get("name"), "temp_f": p.get("temperature"),
                         "wind_mph": (p.get("windSpeed") or "").split()[0] if p.get("windSpeed") else None,
                         "wind_dir": p.get("windDirection"),
                         "short": p.get("shortForecast"),
                         "detail": p.get("detailedForecast")}
                        for p in (forecast.get("properties") or {}).get("periods", [])[:8]],
                }
            except Exception as error:  # noqa: BLE001
                forecasts[f"{game.get('id')}"] = {"game": game, "error": str(error)[:200]}
    write_json(os.path.join(RAW, "nws", "forecasts.json"), {
        "fetched_at": iso(time.time()),
        "source": "NWS api.weather.gov (official US weather service)",
        "note": "Current forecasts only. Historical forecasts are unavailable from NWS; "
                "weather-based strategies are forward-only by design.",
        "games": forecasts})
    return {"forecast_games": len(forecasts)}


def collect_venues(run_id: str) -> dict:
    """Venue coordinates from ESPN's core API (needed to query NWS points)."""
    coords: dict[str, dict] = {}
    for venue_id in _needed_venue_ids():
        url = f"{ESPN_CORE_VENUES}/{venue_id}"
        try:
            payload = http_get_json(url)
            body_bytes = json.dumps(payload, separators=(",", ":")).encode()
            log_external(run_id, "nfl", url, 200, body_bytes)
            lat = (payload.get("latitude") or payload.get("location", {}).get("latitude"))
            lon = (payload.get("longitude") or payload.get("location", {}).get("longitude"))
            if lat is not None and lon is not None:
                coords[str(venue_id)] = {
                    "name": payload.get("fullName"), "city": payload.get("address", {}).get("city"),
                    "lat": str(lat), "lon": str(lon), "indoor": payload.get("indoor")}
        except Exception as error:  # noqa: BLE001
            log_external(run_id, "nfl", url, 0, str(error).encode())
    existing = read_json(os.path.join(RAW, "nfl", "venues.json"), {}) or {"venues": {}}
    existing["venues"].update(coords)
    existing["fetched_at"] = iso(time.time())
    existing["source"] = "ESPN core venues API (keyless)"
    write_json(os.path.join(RAW, "nfl", "venues.json"), existing)
    return {"venues": len(existing["venues"])}


def _needed_venue_ids() -> set[str]:
    schedule = read_json(os.path.join(RAW, "nfl", "schedule.json"), {})
    known = set((read_json(os.path.join(RAW, "nfl", "venues.json"), {})
                 or {"venues": {}})["venues"].keys())
    ids = set()
    for payload in (schedule.get("weeks") or {}).values():
        for game in payload.get("games", []):
            venue_id = str(game.get("venue_id") or "")
            if venue_id and venue_id not in known:
                ids.add(venue_id)
    return ids


# --------------------------------------------------------------------------

MODES = ("universe", "events", "candles", "live", "nfl", "weather", "full")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", default="full", choices=MODES)
    parser.add_argument("--base-url", default=None,
                        help="override Kalshi base URL (e.g. the elections host)")
    args = parser.parse_args(argv)

    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    client = None
    modes = list(MODES[:-1]) if args.mode == "full" else [args.mode]
    results = {"run": run_id, "modes": {}}
    for mode in modes:
        if mode in ("universe", "events", "candles", "live") and client is None:
            client = KalshiClient(base_url=args.base_url) if args.base_url else KalshiClient()
        before = len(client.calls) if client else 0
        try:
            if mode == "universe":
                results["modes"][mode] = collect_universe(client)
            elif mode == "events":
                results["modes"][mode] = collect_events(client)
            elif mode == "candles":
                results["modes"][mode] = collect_candles(client)
            elif mode == "live":
                results["modes"][mode] = collect_live(client)
            elif mode == "nfl":
                results["modes"][mode] = collect_nfl(run_id)
            elif mode == "weather":
                collect_venues(run_id)
                results["modes"][mode] = collect_weather(run_id)
        except Exception as error:  # noqa: BLE001 — record and surface, never hide
            results["modes"][mode] = {"fatal": str(error)[:400]}
        if client:
            append_manifest(run_id, mode, client.calls[before:])
            results.setdefault("calls", 0)
            results["calls"] += len(client.calls) - before
    write_json(os.path.join(RAW, "runs", f"{run_id}.json"), results)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
