#!/usr/bin/env python3
"""Shared data model over the collected raw snapshots.

The Store loads data/raw once and serves every strategy — market data is NEVER
duplicated per user.  It provides:

  * markets/events (latest verified state, verbatim fields),
  * hourly candlesticks per market with quote resolution at a decision time,
  * games joined across Kalshi series + ESPN metadata (home/away/week/scores),
  * season history up to a decision time (records, rest days, last results).

No values are invented here: missing data raises MissingData flags upstream.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")

REPLAY_DECISION_OFFSETS_H = (26, 2)   # decision points before kickoff (candle aligned)
MAX_QUOTE_STALENESS_H = 6             # last candle older than this => not executable
REPLAY_VOLUME_FRACTION = 0.10         # replay liquidity assumption (documented)
REPLAY_MAX_CONTRACTS = 2000           # absolute replay cap per leg

_MONEYLINE_RE = re.compile(r"^KXNFLGAME-[0-9A-Z]+-([A-Z]{2,3})$")
_TEAM_STRIKE_RE = re.compile(r"^KXNFL[A-Z0-9]*-[0-9A-Z]+-([A-Z]{2,3})(\d+)$")
_TOTAL_RE = re.compile(r"^KXNFL[A-Z0-9]*-[0-9A-Z]+-(\d+)$")


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


class MissingData(Exception):
    """Raised when required verified data is absent (callers flag, never guess)."""


class Market:
    __slots__ = ("ticker", "event_ticker", "series", "title", "status", "result",
                 "settlement_value", "settlement_ts", "open_time", "close_time",
                 "kickoff", "volume", "open_interest", "yes_bid", "yes_ask",
                 "no_bid", "no_ask", "yes_bid_size", "yes_ask_size", "floor_strike",
                 "cap_strike", "strike_type", "sub_title", "raw", "fetched_at")

    def __init__(self, raw: dict, fetched_at: str):
        self.raw = raw
        self.fetched_at = fetched_at
        self.ticker = raw.get("ticker")
        self.event_ticker = raw.get("event_ticker")
        self.series = raw.get("series_ticker")
        self.title = raw.get("title")
        self.sub_title = raw.get("yes_sub_title")
        self.status = raw.get("status")
        self.result = raw.get("result")           # "" | "yes" | "no"
        self.settlement_value = raw.get("settlement_value_dollars")
        self.settlement_ts = raw.get("settlement_ts")
        self.open_time = raw.get("open_time")
        self.close_time = raw.get("close_time")
        self.kickoff = raw.get("occurrence_datetime")
        try:
            self.volume = float(raw.get("volume_fp") or 0)
        except (TypeError, ValueError):
            self.volume = 0.0
        try:
            self.open_interest = float(raw.get("open_interest_fp") or 0)
        except (TypeError, ValueError):
            self.open_interest = 0.0
        self.yes_bid = raw.get("yes_bid_dollars")
        self.yes_ask = raw.get("yes_ask_dollars")
        self.no_bid = raw.get("no_bid_dollars")
        self.no_ask = raw.get("no_ask_dollars")
        self.yes_bid_size = raw.get("yes_bid_size_fp")
        self.yes_ask_size = raw.get("yes_ask_size_fp")
        self.floor_strike = raw.get("floor_strike")
        self.cap_strike = raw.get("cap_strike")
        self.strike_type = raw.get("strike_type")

    # ---- classification helpers (structure verified against the live API)
    @property
    def ml_team(self) -> str | None:
        """Kalshi team code when this is a moneyline (game winner) market."""
        match = _MONEYLINE_RE.match(self.ticker or "")
        return match.group(1) if match else None

    @property
    def spread_team_strike(self) -> tuple[str, int] | None:
        """(team, number) for spread-style markets (team wins by over N-0.5)."""
        match = _TEAM_STRIKE_RE.match(self.ticker or "")
        if match and self.series and "SPREAD" in self.series:
            return match.group(1), int(match.group(2))
        return None

    @property
    def teamtotal_team_strike(self) -> tuple[str, int] | None:
        match = _TEAM_STRIKE_RE.match(self.ticker or "")
        if match and self.series and "TEAMTOTAL" in self.series.upper():
            return match.group(1), int(match.group(2))
        return None

    @property
    def total_strike(self) -> int | None:
        match = _TOTAL_RE.match(self.ticker or "")
        if match and self.series and self.series.endswith("TOTAL") \
                and "TEAM" not in self.series:
            return int(match.group(1))
        return None

    def settled(self) -> bool:
        return bool(self.result) and self.settlement_ts is not None

    def settlement_payout(self, side: str) -> float | None:
        """Dollar payout per contract for `side` at settlement (1.00 / 0.00 / 0.50)."""
        if not self.result:
            return None
        try:
            value = float(self.settlement_value)
        except (TypeError, ValueError):
            return None
        # settlement_value_dollars is the YES payout; ties settle 0.50 per rules.
        return value if side == "yes" else 1.0 - value


class Quote:
    """A resolved executable quote for one market at one decision time."""
    __slots__ = ("market", "ts", "yes_bid", "yes_ask", "no_bid", "no_ask",
                 "close", "bar_volume", "bar_ts", "stale_hours", "source")

    def __init__(self, market: Market, ts: int, yes_bid: float, yes_ask: float,
                 close: float, bar_volume: float, bar_ts: int, source: str):
        self.market = market
        self.ts = ts
        self.yes_bid, self.yes_ask = yes_bid, yes_ask
        self.no_bid, self.no_ask = round(1.0 - yes_ask, 2), round(1.0 - yes_bid, 2)
        self.close = close
        self.bar_volume = bar_volume
        self.bar_ts = bar_ts
        self.stale_hours = (ts - (bar_ts - 3600)) / 3600.0   # worst-case quote age
        self.source = source

    def ask(self, side: str) -> float:
        return self.yes_ask if side == "yes" else self.no_ask

    def bid(self, side: str) -> float:
        return self.yes_bid if side == "yes" else self.no_bid

    def spread_cents(self, side: str = "yes") -> float:
        return round((self.ask(side) - self.bid(side)) * 100, 2)


class Game:
    """One NFL game: Kalshi events across series joined with ESPN metadata."""
    __slots__ = ("slug", "event_ticker_base", "away", "home", "date", "kickoff_epoch",
                 "week", "espn_id", "espn_url", "status", "home_score", "away_score",
                 "venue", "indoor", "markets", "flags", "_by_series")

    def __init__(self, slug: str, away: str, home: str, date: dt.date):
        self.slug = slug
        self.away, self.home = away, home
        self.date = date
        self.event_ticker_base = None    # e.g. KXNFLGAME-26SEP20INDKC (set on join)
        self.kickoff_epoch = None
        self.week = None
        self.espn_id = None
        self.espn_url = None
        self.status = None
        self.home_score = self.away_score = None
        self.venue = None
        self.indoor = None
        self.markets: list[Market] = []
        self.flags: list[str] = []
        self._by_series: dict[str, list[Market]] = {}

    def add_market(self, market: Market) -> None:
        self.markets.append(market)
        self._by_series.setdefault(market.series, []).append(market)

    def markets_of(self, *series) -> list[Market]:
        out = []
        for one in series:
            out.extend(self._by_series.get(one, []))
        return out

    def moneylines(self) -> list[Market]:
        return [m for m in self._by_series.get("KXNFLGAME", []) if m.ml_team]

    def spreads(self) -> list[Market]:
        return [m for m in self._by_series.get("KXNFLSPREAD", [])
                if m.spread_team_strike]

    def totals(self) -> list[Market]:
        return [m for m in self._by_series.get("KXNFLTOTAL", []) if m.total_strike]

    def label(self) -> str:
        return f"{self.away} @ {self.home} {self.date.isoformat()}"

    def is_settled(self) -> bool:
        ml = self.moneylines()
        return bool(ml) and all(m.settled() for m in ml)

    def winner(self) -> str | None:
        for market in self.moneylines():
            if market.settled() and market.result == "yes":
                return market.ml_team
        return None


class Store:
    """Loads every raw snapshot once; shared by all strategies and audits."""

    def __init__(self, raw_dir: str = RAW):
        self.raw_dir = raw_dir
        self.markets: dict[str, Market] = {}
        self.events: dict[str, dict] = {}
        self.candles: dict[str, list[dict]] = {}
        self.games: dict[str, Game] = {}
        self.espn_weeks: dict[int, list[dict]] = {}
        self.universe: dict = {}
        self.mismatches: list[dict] = []
        self.data_notes: list[str] = []

    # ------------------------------------------------------------ loading
    def load(self) -> "Store":
        self._load_universe()
        self._load_events_and_markets()
        self._load_candles()
        self._build_games()
        self._load_espn()
        self._join_espn()
        return self

    def _load_universe(self) -> None:
        path = os.path.join(self.raw_dir, "kalshi", "universe.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                self.universe = json.load(handle)
        else:
            self.data_notes.append("kalshi/universe.json missing (collect --mode universe)")

    def _load_events_and_markets(self) -> None:
        markets_dir = os.path.join(self.raw_dir, "kalshi", "markets")
        if not os.path.isdir(markets_dir):
            self.data_notes.append("kalshi/markets/ missing (collect --mode events)")
            return
        for name in sorted(os.listdir(markets_dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(markets_dir, name), encoding="utf-8") as handle:
                payload = json.load(handle)
            event_ticker = payload.get("event_ticker")
            self.events[event_ticker] = payload
            for row in payload.get("markets", []):
                ticker = row.get("ticker")
                if ticker:
                    # later files (sorted) overwrite earlier snapshots of the same
                    # market — the latest verified state wins; the manifest keeps
                    # the full fetch history
                    self.markets[ticker] = Market(row, payload.get("fetched_at"))

    def _load_candles(self) -> None:
        candles_dir = os.path.join(self.raw_dir, "kalshi", "candles")
        if not os.path.isdir(candles_dir):
            self.data_notes.append("kalshi/candles/ missing (collect --mode candles)")
            return
        for series_dir in sorted(os.listdir(candles_dir)):
            full = os.path.join(candles_dir, series_dir)
            if not os.path.isdir(full):
                continue
            for name in sorted(os.listdir(full)):
                if not name.endswith(".json"):
                    continue
                with open(os.path.join(full, name), encoding="utf-8") as handle:
                    payload = json.load(handle)
                bars = payload.get("bars", [])
                if bars:
                    self.candles[payload["ticker"]] = bars

    def _build_games(self) -> None:
        from engine.collect import slug_date
        from engine.teams import split_slug_teams
        # group markets by their event's game slug
        by_slug: dict[str, list[Market]] = {}
        for event_ticker, payload in self.events.items():
            slug = event_ticker.split("-", 1)[1] if "-" in event_ticker else ""
            date = slug_date(event_ticker)
            teams = split_slug_teams(slug)
            if date is None or teams is None:
                continue  # non-game or unparseable events are not competition games
            by_slug.setdefault(slug, []).extend(
                self.markets[m["ticker"]] for m in payload.get("markets", [])
                if m.get("ticker") in self.markets)
        for slug, markets in by_slug.items():
            date = slug_date("KXNFLGAME-" + slug)
            teams = split_slug_teams(slug)
            game = Game(slug, teams[0], teams[1], date)
            seen = set()
            for market in markets:
                if market.ticker in seen:
                    continue
                seen.add(market.ticker)
                game.add_market(market)
                if market.kickoff and game.kickoff_epoch is None:
                    kick = epoch(market.kickoff)
                    if kick:
                        game.kickoff_epoch = kick
            game.event_ticker_base = f"KXNFLGAME-{slug}"
            self.games[slug] = game

    def _load_espn(self) -> None:
        path = os.path.join(self.raw_dir, "nfl", "schedule.json")
        if not os.path.exists(path):
            self.data_notes.append("nfl/schedule.json missing (collect --mode nfl)")
            return
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        for week_text, week_payload in (payload.get("weeks") or {}).items():
            try:
                week = int(week_text)
            except ValueError:
                continue
            self.espn_weeks[week] = week_payload.get("games", [])

    def _join_espn(self) -> None:
        from engine.teams import ESPN_TO_KALSHI
        espn_games = []
        for week, games in self.espn_weeks.items():
            for game in games:
                espn_games.append((week, game))
        for game in self.games.values():
            matched = None
            for week, espn in espn_games:
                home = ESPN_TO_KALSHI.get(espn.get("home") or "")
                away = ESPN_TO_KALSHI.get(espn.get("away") or "")
                date_text = (espn.get("date") or "")[:10]
                if home == game.home and away == game.away and date_text == game.date.isoformat():
                    matched = (week, espn)
                    break
            if matched:
                week, espn = matched
                game.week = week
                game.espn_id = espn.get("id")
                game.espn_url = espn.get("espn_url")
                game.status = espn.get("status")
                game.home_score = espn.get("home_score")
                game.away_score = espn.get("away_score")
                game.venue = espn.get("venue")
                game.indoor = espn.get("indoor")
                # cross-check kickoff times (Kalshi occurrence vs ESPN date)
                espn_kick = epoch(espn.get("date"))
                if game.kickoff_epoch and espn_kick and abs(game.kickoff_epoch - espn_kick) > 6 * 3600:
                    self.mismatches.append({
                        "kind": "kickoff_mismatch", "game": game.slug,
                        "kalshi_kickoff": game.kickoff, "espn_date": espn.get("date")})
            else:
                self.mismatches.append({"kind": "no_espn_match", "game": game.slug})

    # ------------------------------------------------------------ queries
    def settled_games(self, before_ts: int | None = None) -> list[Game]:
        out = []
        for game in self.games.values():
            if not game.is_settled():
                continue
            if before_ts is not None and game.kickoff_epoch and game.kickoff_epoch > before_ts:
                continue
            out.append(game)
        return sorted(out, key=lambda g: g.kickoff_epoch or 0)

    def quote_at(self, market: Market, ts: int) -> Quote | None:
        """Executable quote at decision time ts from hourly candlesticks.

        Uses the last completed bar at or before ts.  Returns None when no bar
        exists (never fabricates a quote).
        """
        bars = self.candles.get(market.ticker)
        if not bars:
            return None
        best = None
        for bar in bars:
            bar_ts = bar.get("t")
            if bar_ts is None:
                continue
            if bar_ts <= ts and (best is None or bar_ts > best["t"]):
                best = bar
        if best is None:
            return None
        try:
            yes_bid = float(best.get("yb"))
            yes_ask = float(best.get("ya"))
            close = float(best.get("c"))
            volume = float(best.get("v") or 0)
        except (TypeError, ValueError):
            return None
        if yes_bid <= 0 or yes_ask >= 1 or yes_ask < yes_bid:
            return None    # degenerate/edge quotes are not treated as executable
        return Quote(market, ts, yes_bid, yes_ask, close, volume, int(best["t"]),
                     source="kalshi_candlesticks_hourly")

    def season_history(self, team: str, before_ts: int) -> dict:
        """Verified pre-game history for a team from settled ESPN results.

        Only uses games whose ESPN status is STATUS_FINAL and whose kickoff is
        before `before_ts` (no lookahead).
        """
        from engine.teams import ESPN_TO_KALSHI
        kalshi_code = team
        espn_code = next((espn for espn, k in ESPN_TO_KALSHI.items() if k == kalshi_code),
                         kalshi_code)
        played = []
        for week, games in sorted(self.espn_weeks.items()):
            for game in games:
                if game.get("status") != "STATUS_FINAL":
                    continue
                if (game.get("home") or "").upper() != espn_code.upper() and \
                        (game.get("away") or "").upper() != espn_code.upper():
                    continue
                kick = epoch(game.get("date"))
                if kick is None or kick >= before_ts:
                    continue
                try:
                    home_score = int(game.get("home_score") or 0)
                    away_score = int(game.get("away_score") or 0)
                except (TypeError, ValueError):
                    continue
                is_home = (game.get("home") or "").upper() == espn_code.upper()
                own, opp = (home_score, away_score) if is_home else (away_score, home_score)
                played.append({
                    "week": week, "date": game.get("date"), "is_home": is_home,
                    "own": own, "opp": opp, "win": own > opp, "tie": own == opp,
                    "margin": own - opp, "total": own + opp,
                    "espn_id": game.get("id")})
        wins = sum(1 for p in played if p["win"])
        ties = sum(1 for p in played if p["tie"])
        losses = len(played) - wins - ties
        last = played[-1] if played else None
        rest_days = None
        if last:
            last_ts = epoch(last["date"])
            if last_ts:
                rest_days = max(0, round((before_ts - last_ts) / 86400.0))
        return {
            "team": team, "games": played, "record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
            "wins": wins, "losses": losses, "ties": ties,
            "points_for": sum(p["own"] for p in played),
            "points_against": sum(p["opp"] for p in played),
            "avg_margin": (sum(p["margin"] for p in played) / len(played)) if played else None,
            "last_game": last, "rest_days": rest_days,
            "win_streak": _streak(played),
        }


def _streak(played: list[dict]) -> int:
    """Positive = consecutive wins ending now; negative = consecutive losses."""
    streak = 0
    for game in reversed(played):
        if game["tie"]:
            break
        won = game["win"]
        if streak == 0:
            streak = 1 if won else -1
        elif (streak > 0 and won) or (streak < 0 and not won):
            streak += 1 if won else -1
        else:
            break
    return streak
