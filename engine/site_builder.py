#!/usr/bin/env python3
"""
Site builder: generates static JSON bundles for GitHub Pages site.

Outputs to site_data/ and docs/ (GitHub Pages). Copy site_data into
docs/site_data so the static site can fetch them with relative paths.
"""
from __future__ import annotations

import json
import os
import time
import shutil
from typing import Any, Dict, List

from .competition import load_users, get_leaderboard
from .ledger import read_ledger, latest_trades
from .verify import full_verification
from .utils import iso_now

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
# GitHub Pages serves docs/, so the bundles are written straight into docs/site_data.
# A second copy at the repository root would double the committed bytes for no gain.
SITE_DATA = os.path.join(DOCS, "site_data")
COMP = os.path.join(ROOT, "data", "competition")
RAW = os.path.join(ROOT, "data", "raw")

def _fresh_dir(path: str) -> str:
    """Create a directory, removing any stale output from a previous, larger run.

    Without this, shrinking the competition (or changing the profile schema) leaves
    orphaned bundles behind — e.g. 1,500 profile files for a 1,000-user competition,
    500 of them from an older schema and still servable.
    """
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)
    return path


def ensure_dirs():
    os.makedirs(DOCS, exist_ok=True)
    _fresh_dir(SITE_DATA)
    _fresh_dir(os.path.join(SITE_DATA, "users"))
    _fresh_dir(os.path.join(SITE_DATA, "trades"))


# Leaderboard projection. The full user record carries a multi-paragraph strategy
# explanation; repeating that for every row would inflate the leaderboard bundle by an
# order of magnitude at 1,000 users, so only the columns the table renders are emitted.
LEADERBOARD_FIELDS = (
    "user_id", "username", "strategy_id", "strategy_name", "strategy_description",
    "starting_bankroll", "current_bankroll", "total_pnl", "roi_percent",
    "wins", "losses", "win_rate", "total_trades", "rank",
    "last_trade_at", "competition_status",
)


def _leaderboard_row(user: dict) -> dict:
    row = {k: user.get(k) for k in LEADERBOARD_FIELDS}
    row["open_positions"] = len(user.get("open_trades") or [])
    return row


# Trade projection used by the single, shared trade index. Everything needed to verify
# a trade by hand is kept (identifiers, prices, quantities, timestamps, snapshot file,
# official URLs); the bulky per-trade flag array is replaced by a count plus types,
# since the full flags live in the ledger and are aggregated on the Verification page.
def _compact_leg(leg: dict) -> dict:
    return {
        "t": leg.get("market_ticker"),
        "e": leg.get("event_ticker"),
        "s": leg.get("series_ticker"),
        "side": leg.get("side"),
        "px": leg.get("entry_price"),
        "exec": leg.get("exec_price"),
        "qty": leg.get("quantity"),
        "qty_req": leg.get("quantity_requested"),
        "bid": leg.get("bid_at_entry"),
        "ask": leg.get("ask_at_entry"),
        "spr": leg.get("spread"),
        "ip": leg.get("implied_prob"),
        "liq": leg.get("liquidity_at_entry"),
        "req": leg.get("reason"),
        "mp": leg.get("model_prob"),
        "src": leg.get("source_file"),
        "sha": leg.get("source_sha256"),
        "ts": leg.get("entry_timestamp"),
        "u": leg.get("source_url"),
        "v": leg.get("verification_url"),
    }


def _compact_trade(t: dict) -> dict:
    flags = t.get("flags") or []
    return {
        "trade_id": t.get("trade_id"),
        "user_id": t.get("user_id"),
        "username": t.get("username"),
        "strategy_id": t.get("strategy_id"),
        "status": t.get("status"),
        "result": t.get("result"),
        "market_type": t.get("market_type"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "entry_price_combined": t.get("entry_price_combined"),
        "exit_price_combined": t.get("exit_price_combined"),
        "exit_timestamp": t.get("exit_timestamp"),
        "settlement_price": t.get("settlement_price"),
        "position_size_dollars": t.get("position_size_dollars"),
        "fees": t.get("fees"),
        "payout_dollars": t.get("payout_dollars"),
        "contracts": t.get("contracts"),
        "pnl_dollars": t.get("pnl_dollars"),
        "roi_percent": t.get("roi_percent"),
        "expected_value": t.get("expected_value"),
        "why_entered": t.get("why_entered"),
        "why_exited": t.get("why_exited"),
        "settlement_result_source": t.get("settlement_result_source"),
        "settlement_note": t.get("settlement_note"),
        "fee_model": t.get("fee_model"),
        "order_type": t.get("order_type"),
        "is_native_kalshi_combo": t.get("is_native_kalshi_combo"),
        "legs": [_compact_leg(l) for l in t.get("legs", [])],
        "official_sources": t.get("official_sources") or [],
        "flag_count": len(flags),
        "flag_types": sorted({f.get("flag_type") for f in flags if f.get("flag_type")}),
        "ledger_hash": t.get("hash"),
        "ledger_seq": t.get("ledger_seq"),
    }


def build_leaderboard():
    users = load_users()
    sorted_users = sorted(users, key=lambda u: u.get("rank", 9999))
    rows = [_leaderboard_row(u) for u in sorted_users]
    with open(os.path.join(SITE_DATA, "leaderboard.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(rows), "users": rows}, f)

    # Paginated pages
    page_size = 25
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    for page in range(1, total_pages + 1):
        start = (page - 1) * page_size
        end = start + page_size
        page_data = {
            "page": page,
            "page_size": page_size,
            "total": len(rows),
            "total_pages": total_pages,
            "users": rows[start:end],
        }
        with open(os.path.join(SITE_DATA, f"leaderboard_page_{page}.json"), "w", encoding="utf-8") as f:
            json.dump(page_data, f)

def build_user_profiles():
    """One small summary file per user, plus a reference to the shared trade index.

    Trade bodies are NOT duplicated here. Every profile points at the single
    `trades/index.json` file and the browser filters it by user_id, so adding users
    does not multiply trade storage.
    """
    users = load_users()
    trades = latest_trades()
    by_user: Dict[str, List[dict]] = {}
    for t in trades:
        by_user.setdefault(t.get("user_id"), []).append(t)

    for user in users:
        uid = user["user_id"]
        user_trades = by_user.get(uid, [])
        open_trades = [t for t in user_trades if t.get("status") in ("ORDER", "EXECUTED")]
        closed_trades = [t for t in user_trades if t.get("status") in ("SETTLED", "CLOSED")]
        settled = [t for t in user_trades if t.get("pnl_dollars") is not None]
        equity = user.get("performance_history", [])

        # Drawdown from the stored equity curve (peak-to-trough on bankroll).
        peak = None
        max_dd = 0.0
        for point in equity:
            value = point.get("bankroll")
            if value is None:
                continue
            peak = value if peak is None else max(peak, value)
            if peak:
                max_dd = max(max_dd, (peak - value) / peak)

        gross_win = sum(t["pnl_dollars"] for t in settled if (t.get("pnl_dollars") or 0) > 0)
        gross_loss = sum(t["pnl_dollars"] for t in settled if (t.get("pnl_dollars") or 0) < 0)

        # The strategy body is shared by every user on that strategy, so it is served
        # once from strategies.json rather than repeated in all 1,000 profile files.
        user_summary = {k: v for k, v in user.items()
                        if k not in ("strategy_long_explanation", "performance_history")}

        profile = {
            "user": user_summary,
            "strategy_ref": user.get("strategy_id"),
            "strategy_long_explanation_from": "site_data/strategies.json",
            "equity_curve": equity,
            "trade_ids": [t.get("trade_id") for t in
                          sorted(user_trades, key=lambda x: x.get("created_at", ""), reverse=True)],
            "stats": {
                "wins": user.get("wins", 0),
                "losses": user.get("losses", 0),
                "win_rate": user.get("win_rate"),
                "total_trades": user.get("total_trades"),
                "roi": user.get("roi_percent"),
                "pnl": user.get("total_pnl"),
                "open_positions": len(open_trades),
                "closed_positions": len(closed_trades),
                "open_exposure": round(sum(t.get("position_size_dollars") or 0
                                           for t in open_trades), 2),
                "total_volume": round(sum(t.get("position_size_dollars") or 0
                                          for t in user_trades), 2),
                "total_fees": round(sum(t.get("fees") or 0 for t in user_trades), 2),
                "max_drawdown_pct": round(max_dd * 100, 2),
                "gross_profit": round(gross_win, 2),
                "gross_loss": round(gross_loss, 2),
                "avg_trade_pnl": round(user.get("total_pnl", 0) / len(settled), 2) if settled else 0.0,
                "avg_roi_per_trade": round(
                    sum(t.get("roi_percent") or 0 for t in settled) / len(settled), 2
                ) if settled else 0.0,
                "settlement_sources": {
                    src: sum(1 for t in settled if t.get("settlement_result_source") == src)
                    for src in ("OFFICIAL", "SIMULATED", "PARTIAL", "UNKNOWN")
                },
            },
            "note": ("Trade records are served from the shared bundle "
                     "site_data/trades/index.json, filtered by this user_id, so the same "
                     "verified market data is not duplicated per user."),
            "updated_at": iso_now(),
        }
        with open(os.path.join(SITE_DATA, "users", f"{uid}.json"), "w", encoding="utf-8") as f:
            json.dump(profile, f)

def build_trades():
    """Write the trade bundles the site reads.

    Layout (sized so 1,000 users do not produce an unmanageable site):

    ``trades/index.json``      every trade, one compact-but-verifiable row each. A
                               single shared file: profiles filter it by user_id rather
                               than each carrying their own copy of the trades.
    ``trades/<view>.json``     recent / upcoming / closed / rejected, bounded at 200
                               rows each, carrying the FULL record so any listed trade
                               can be inspected without another request.
    ``trades/ledger_summary``  counts, including the distinction between distinct
                               trades and total hash-chained ledger entries.
    """
    trades = latest_trades()
    raw_entries = read_ledger()
    sorted_trades = sorted(trades, key=lambda x: x.get("created_at", ""), reverse=True)

    recent = sorted_trades[:200]
    upcoming = [t for t in sorted_trades
                if t.get("status") in ("CANDIDATE", "SIGNAL", "ORDER", "EXECUTED")][:200]
    closed = [t for t in sorted_trades if t.get("status") in ("SETTLED", "CLOSED")][:200]
    rejected = [t for t in sorted_trades if t.get("status") == "REJECTED"][:200]

    for name, data in [("recent", recent), ("upcoming", upcoming),
                        ("closed", closed), ("rejected", rejected)]:
        with open(os.path.join(SITE_DATA, "trades", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump({"updated_at": iso_now(), "count": len(data), "trades": data}, f)

    # Shared index: full trade population as compact rows, newest first.
    index_rows = [_compact_trade(t) for t in sorted_trades]
    with open(os.path.join(SITE_DATA, "trades", "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": iso_now(),
            "count": len(index_rows),
            "field_map": {
                "t": "market_ticker", "e": "event_ticker", "s": "series_ticker",
                "px": "entry_price", "exec": "executed price", "qty": "quantity filled",
                "qty_req": "quantity requested", "bid": "bid at entry", "ask": "ask at entry",
                "spr": "quoted spread", "ip": "implied probability", "liq": "liquidity at entry",
                "req": "strategy reason", "mp": "model probability", "src": "snapshot file",
                "sha": "snapshot sha256", "ts": "entry timestamp", "u": "official source url",
                "v": "verification url",
            },
            "trades": index_rows,
        }, f)

    statuses = ["CANDIDATE", "SIGNAL", "ORDER", "EXECUTED", "CLOSED", "SETTLED",
                "CANCELLED", "REJECTED"]
    with open(os.path.join(SITE_DATA, "trades", "ledger_summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": iso_now(),
            "total": len(trades),
            "ledger_entries": len(raw_entries),
            "by_status": {s: len([t for t in trades if t.get("status") == s]) for s in statuses},
            "note": ("`total` counts distinct trades (latest state per trade_id). "
                     "`ledger_entries` counts every hash-chained state transition, "
                     "including the full audit trail."),
        }, f)

def build_markets():
    season_path = os.path.join(RAW, "kalshi", "season_events.json")
    markets_data = {"markets": [], "events": [], "updated_at": iso_now()}
    if os.path.exists(season_path):
        with open(season_path, "r", encoding="utf-8") as f:
            season = json.load(f)
            markets_data["events"] = season.get("event_tickers", [])[:100]
            markets_data["series_summary"] = season.get("series_summary", {})

    markets_dir = os.path.join(RAW, "kalshi", "markets")
    if os.path.exists(markets_dir):
        sample = []
        for fn in os.listdir(markets_dir)[:20]:
            fp = os.path.join(markets_dir, fn)
            try:
                with open(fp, "r", encoding="utf-8") as pf:
                    payload = json.load(pf)
                    sample.extend(payload.get("markets", [])[:5])
            except:
                continue
        markets_data["markets"] = sample

    with open(os.path.join(SITE_DATA, "markets.json"), "w", encoding="utf-8") as f:
        json.dump(markets_data, f)

def build_strategies():
    from .strategies import get_all_strategies
    strategies = get_all_strategies()
    users = load_users()
    strat_perf = {}
    for u in users:
        sid = u["strategy_id"]
        if sid not in strat_perf:
            strat_perf[sid] = {"users": 0, "total_pnl": 0, "wins": 0, "losses": 0, "trades": 0, "roi": []}
        strat_perf[sid]["users"] += 1
        strat_perf[sid]["total_pnl"] += u.get("total_pnl", 0)
        strat_perf[sid]["wins"] += u.get("wins", 0)
        strat_perf[sid]["losses"] += u.get("losses", 0)
        strat_perf[sid]["trades"] += u.get("total_trades", 0)
        strat_perf[sid]["roi"].append(u.get("roi_percent", 0))

    strategies_data = []
    for s in strategies:
        perf = strat_perf.get(s.strategy_id, {})
        avg_roi = sum(perf.get("roi", [])) / len(perf.get("roi", [])) if perf.get("roi") else 0
        strategies_data.append({
            **s.to_dict(),
            "performance": {
                "users": perf.get("users", 0),
                "total_pnl": round(perf.get("total_pnl", 0), 2),
                "wins": perf.get("wins", 0),
                "losses": perf.get("losses", 0),
                "trades": perf.get("trades", 0),
                "avg_roi": round(avg_roi, 2),
            }
        })

    with open(os.path.join(SITE_DATA, "strategies.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(strategies_data), "strategies": strategies_data}, f)

def build_verification():
    """Verification bundle.

    Raw flag lists grow with the trade population (hundreds of identical
    "market file missing" rows at 1,000 users), so they are aggregated by flag type
    with a bounded sample of individual occurrences. Nothing is dropped from the
    audit itself: `data/competition/verification_report.json` and the ledger keep the
    complete list.
    """
    verification = full_verification()

    raw_flags = verification.get("trades", {}).get("flags", []) or []
    by_type: Dict[str, dict] = {}
    for flag in raw_flags:
        ftype = flag.get("flag_type", "UNKNOWN")
        bucket = by_type.setdefault(ftype, {
            "flag_type": ftype,
            "severity": flag.get("severity"),
            "count": 0,
            "trades_affected": set(),
            "sample_messages": [],
        })
        bucket["count"] += 1
        if flag.get("trade_id"):
            bucket["trades_affected"].add(flag["trade_id"])
        if len(bucket["sample_messages"]) < 5 and flag.get("message") not in bucket["sample_messages"]:
            bucket["sample_messages"].append(flag.get("message"))

    aggregated = []
    for ftype, bucket in sorted(by_type.items(), key=lambda kv: -kv[1]["count"]):
        aggregated.append({
            "flag_type": ftype,
            "severity": bucket["severity"],
            "count": bucket["count"],
            "trades_affected": len(bucket["trades_affected"]),
            "sample_messages": bucket["sample_messages"],
        })

    verification["trades"]["flags_aggregated"] = aggregated
    verification["trades"]["flags_total"] = len(raw_flags)
    # Keep a bounded sample rather than the whole list in the served bundle.
    verification["trades"]["flags"] = raw_flags[:50]
    verification["trades"]["flags_truncated"] = len(raw_flags) > 50
    verification["flags"] = []

    with open(os.path.join(SITE_DATA, "verification.json"), "w", encoding="utf-8") as f:
        json.dump(verification, f)

    sources = {
        "kalshi_api": {
            "base_url": "https://api.elections.kalshi.com/trade-api/v2",
            "docs": "https://docs.kalshi.com/",
            "endpoints": [
                "/exchange/status", "/series", "/events", "/markets",
                "/markets/{ticker}", "/markets/{ticker}/orderbook",
                "/series/{series}/markets/{ticker}/candlesticks", "/markets/trades"
            ],
            "note": "Only official Kalshi Trade API v2, read-only, no credentials"
        },
        "espn_api": {
            "base_url": "https://site.api.espn.com/apis/site/v2/sports/football/nfl",
            "endpoints": ["/scoreboard", "/injuries"],
            "note": "NFL metadata only — not price source"
        },
        "nws_api": {
            "base_url": "https://api.weather.gov",
            "note": "Weather forecasts forward-only, historical unavailable"
        },
    }
    with open(os.path.join(SITE_DATA, "data_sources.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "sources": sources}, f)

def build_competition_overview():
    users = load_users()
    entries = read_ledger()
    trades = latest_trades(entries)
    total_pnl = sum(u.get("total_pnl", 0) for u in users)
    overview = {
        "updated_at": iso_now(),
        "season": "2026",
        "status": "ACTIVE",
        "total_users": len(users),
        "total_trades": len(trades),
        "ledger_entries": len(entries),
        "data_provenance": {
            "real_kalshi_data_present": os.path.exists(
                os.path.join(RAW, "kalshi", "season_events.json")),
            "note": ("Raw verified Kalshi snapshots were found in data/raw; prices trace "
                     "to the fetch manifest.")
            if os.path.exists(os.path.join(RAW, "kalshi", "season_events.json")) else
            ("NO verified Kalshi snapshots in data/raw — the competition is running on "
             "flagged synthetic fixtures for offline/scalability testing. All trades "
             "carry an UNVERIFIED_DATA flag until a collection cycle succeeds."),
        },
        "total_pnl": round(total_pnl, 2),
        "avg_roi": round(sum(u.get("roi_percent", 0) for u in users) / max(1, len(users)), 2),
        "top_performer": sorted(users, key=lambda x: x.get("total_pnl", 0), reverse=True)[0] if users else None,
        "worst_performer": sorted(users, key=lambda x: x.get("total_pnl", 0))[0] if users else None,
        "by_status": {s: len([t for t in trades if t.get("status") == s])
                      for s in ["CANDIDATE", "SIGNAL", "ORDER", "EXECUTED",
                                "CLOSED", "SETTLED", "CANCELLED", "REJECTED"]},
        "scalability_test": {
            "supported": [5, 10, 15, 25, 30, 50, 70, 100, 250, 500, 750, 1000],
            "current": len(users),
            "architecture": "Shared market data + hash-chained ledger, no per-user duplication"
        }
    }
    with open(os.path.join(SITE_DATA, "competition.json"), "w", encoding="utf-8") as f:
        json.dump(overview, f)

def build_docs_site():
    """Build the GitHub Pages site assets in docs/.

    Deliberately does NOT call ensure_dirs(): that clears and recreates the bundle
    directories, and this function runs after the bundles are written in main().
    """
    os.makedirs(DOCS, exist_ok=True)

    html = _build_html()
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    css = _build_css()
    with open(os.path.join(DOCS, "style.css"), "w", encoding="utf-8") as f:
        f.write(css)

    js = _build_js()
    with open(os.path.join(DOCS, "app.js"), "w", encoding="utf-8") as f:
        f.write(js)


def _build_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFL Parlay Trading Competition</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <div class="header-content">
    <h1>🏈 NFL Parlay Trading Competition</h1>
    <p>Auditable paper-trading competition using real verified Kalshi NFL markets. No real money traded.</p>
    <nav>
      <a href="#" data-section="overview" class="nav-link active">Overview</a>
      <a href="#" data-section="leaderboard" class="nav-link">Leaderboard</a>
      <a href="#" data-section="upcoming" class="nav-link">Upcoming Trades</a>
      <a href="#" data-section="recent" class="nav-link">Recent Trades</a>
      <a href="#" data-section="markets" class="nav-link">Markets</a>
      <a href="#" data-section="strategies" class="nav-link">Strategies</a>
      <a href="#" data-section="users" class="nav-link">Users</a>
      <a href="#" data-section="verification" class="nav-link">Verification</a>
      <a href="#" data-section="history" class="nav-link">History</a>
    </nav>
  </div>
</header>

<main>
  <section id="overview" class="page active">
    <h2>Competition Overview</h2>
    <div id="overview-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="leaderboard" class="page">
    <h2>Leaderboard</h2>
    <div class="controls">
      <input type="text" id="search" placeholder="🔍 Search username or strategy...">
      <select id="sort">
        <option value="rank">Rank</option>
        <option value="pnl">PnL</option>
        <option value="roi">ROI</option>
        <option value="win_rate">Win Rate</option>
        <option value="trades">Trades</option>
        <option value="bankroll">Bankroll</option>
      </select>
      <select id="pageSize">
        <option value="25">25/page</option>
        <option value="50">50/page</option>
        <option value="100">100/page</option>
      </select>
    </div>
    <div id="leaderboard-content"><div class="loading">Loading...</div></div>
    <div id="pagination" class="pagination"></div>
  </section>

  <section id="upcoming" class="page">
    <h2>Upcoming / Open Trades</h2>
    <p class="subtitle">Lifecycle: Candidate → Signal → Order → Executed → Closed → Settled</p>
    <div id="upcoming-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="recent" class="page">
    <h2>Recent Trades</h2>
    <div id="recent-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="markets" class="page">
    <h2>Markets</h2>
    <p class="subtitle">Real verified Kalshi NFL markets. Prices from official Trade API v2.</p>
    <div id="markets-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="strategies" class="page">
    <h2>Strategy Library</h2>
    <div id="strategies-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="users" class="page">
    <h2>User Profiles</h2>
    <p class="subtitle">Click a username on the leaderboard to view their full profile.</p>
    <div id="user-profile" class="profile-container"></div>
  </section>

  <section id="verification" class="page">
    <h2>Trade Verification</h2>
    <p class="subtitle">Every trade: Leaderboard → User → Trade → Official Source</p>
    <div id="verification-content"><div class="loading">Loading...</div></div>
    <div id="data-sources-content"></div>
  </section>

  <section id="history" class="page">
    <h2>History & Scalability</h2>
    <div id="history-content"><div class="loading">Loading...</div></div>
  </section>
</main>

<footer>
  <p>NFL Parlay Trading Competition — Paper trading only. No real money.
     Data from Kalshi official API, ESPN keyless, NWS.
     <a href="https://github.com/buffedlizard55-lab/NFLPARLAYCOMP">GitHub Repo</a></p>
  <p class="small">Every price, timestamp, market, settlement from official sources with SHA-256 manifest.
     Simulated trades clearly labeled. <a href="#" data-section="verification" class="nav-link">Verification</a></p>
</footer>

<script src="app.js"></script>
</body>
</html>"""


def _build_css() -> str:
    return """
/* NFL Parlay Competition - Clean, fast, scalable UI */
:root {
  --bg: #f1f5f9; --surface: #ffffff; --text: #0f172a; --text2: #475569;
  --border: #e2e8f0; --primary: #1e40af; --primary-light: #3b82f6;
  --green: #16a34a; --green-bg: #dcfce7; --red: #dc2626; --red-bg: #fee2e2;
  --yellow: #ca8a04; --yellow-bg: #fef9c3; --gray: #64748b;
  --radius: 8px; --shadow: 0 1px 3px rgba(0,0,0,0.08);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.5; font-size: 14px; }
a { color: var(--primary-light); text-decoration: none; }
a:hover { text-decoration: underline; }

header { background: #0f172a; color: white; padding: 1rem 1.5rem; position: sticky; top: 0; z-index: 100; }
.header-content { max-width: 1400px; margin: 0 auto; }
header h1 { font-size: 1.3rem; margin-bottom: 0.25rem; }
header p { font-size: 0.8rem; opacity: 0.7; margin-bottom: 0.75rem; }
nav { display: flex; flex-wrap: wrap; gap: 0.25rem; }
nav a { color: #93c5fd; font-size: 0.8rem; padding: 0.3rem 0.6rem; border-radius: 4px;
        transition: background 0.2s; }
nav a:hover, nav a.active { background: rgba(255,255,255,0.15); text-decoration: none; color: white; }

main { max-width: 1400px; margin: 0 auto; padding: 1rem; }
.page { display: none; }
.page.active { display: block; }
section { background: var(--surface); border-radius: var(--radius); padding: 1.25rem;
          margin-bottom: 1rem; box-shadow: var(--shadow); }
h2 { font-size: 1.15rem; border-bottom: 2px solid var(--border); padding-bottom: 0.5rem; margin-bottom: 1rem; }
.subtitle { color: var(--text2); font-size: 0.85rem; margin-bottom: 1rem; }

.controls { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
.controls input, .controls select { padding: 0.5rem 0.75rem; border: 1px solid var(--border);
  border-radius: 4px; font-size: 0.85rem; background: white; }
.controls input { flex: 1; min-width: 200px; }

table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
th { background: #f8fafc; padding: 0.6rem 0.5rem; text-align: left; font-weight: 600;
     border-bottom: 2px solid var(--border); white-space: nowrap; }
td { padding: 0.5rem; border-bottom: 1px solid var(--border); }
tr:hover { background: #f8fafc; }
.table-container { overflow-x: auto; }

.badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.72rem; font-weight: 600; }
.badge-win { background: var(--green-bg); color: var(--green); }
.badge-loss { background: var(--red-bg); color: var(--red); }
.badge-pending { background: var(--yellow-bg); color: var(--yellow); }
.badge-executed { background: #dbeafe; color: var(--primary); }
.badge-settled { background: #e0e7ff; color: #4338ca; }
.badge-rejected { background: #f3f4f6; color: var(--gray); }
.badge-order { background: #fef3c7; color: #92400e; }
.badge-signal, .badge-candidate { background: #f1f5f9; color: #475569; }
.badge-closed { background: #e2e8f0; color: #334155; }

/* Settlement provenance — simulated can never look official */
.prov-official { background: var(--green-bg); color: var(--green); }
.prov-simulated { background: var(--yellow-bg); color: #a16207; }
.prov-unknown { background: #f3f4f6; color: var(--gray); }

/* Expandable trade drill-down */
tr.clickable { cursor: pointer; }
tr.detail-row { display: none; }
tr.detail-row.open { display: table-row; }
tr.detail-row > td { background: #f8fafc; padding: 1rem; }
.detail h4 { font-size: 0.85rem; margin: 0.75rem 0 0.4rem; color: #334155;
  border-bottom: 1px solid var(--border); padding-bottom: 0.2rem; }
.kv { display: flex; gap: 0.75rem; font-size: 0.78rem; padding: 0.15rem 0; }
.kv > span:first-child { min-width: 170px; color: var(--text2); }
.kv > span:last-child { word-break: break-word; }
.leg { border: 1px solid var(--border); border-radius: 6px; padding: 0.5rem; margin-bottom: 0.5rem; background: white; }
.mini-flag { font-size: 0.75rem; padding: 0.3rem 0.5rem; border-radius: 4px; margin-bottom: 0.25rem; }
.reconcile { margin-top: 0.75rem; font-size: 0.78rem; background: #f1f5f9;
  padding: 0.5rem; border-radius: 6px; }
.reconcile .ok { color: var(--green); margin-left: 0.5rem; font-weight: 600; }
.reconcile .bad { color: var(--red); margin-left: 0.5rem; font-weight: 600; }
.spark { width: 100%; height: 60px; display: block; background: #f8fafc;
  border-radius: 6px; margin-bottom: 0.5rem; }
details > summary { cursor: pointer; font-size: 0.82rem; color: var(--primary-light); }

.positive { color: var(--green); font-weight: 600; }
.negative { color: var(--red); font-weight: 600; }

.pagination { display: flex; gap: 0.25rem; margin-top: 1rem; flex-wrap: wrap; }
.pagination button { padding: 0.4rem 0.75rem; border: 1px solid var(--border); background: white;
  border-radius: 4px; cursor: pointer; font-size: 0.8rem; transition: all 0.15s; }
.pagination button:hover { background: #f1f5f9; }
.pagination button.active { background: var(--primary); color: white; border-color: var(--primary); }

.card { border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem; margin-bottom: 0.75rem; }
.card h3 { margin-bottom: 0.5rem; font-size: 1rem; }

.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; margin-bottom: 1rem; }
.stat-card { background: #f8fafc; border-radius: var(--radius); padding: 0.75rem; text-align: center; }
.stat-card .label { font-size: 0.75rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; }
.stat-card .value { font-size: 1.4rem; font-weight: 700; margin-top: 0.25rem; }

.flag-high { border-left: 4px solid var(--red); background: #fef2f2; }
.flag-medium { border-left: 4px solid var(--yellow); background: #fffbeb; }
.flag-low { border-left: 4px solid var(--gray); background: #f8fafc; }

pre { background: #f1f5f9; padding: 0.75rem; border-radius: 4px; overflow: auto; font-size: 0.78rem; }
.loading { color: var(--text2); padding: 2rem; text-align: center; }

.profile-container .card { margin-bottom: 1rem; }
.profile-container h3 { font-size: 1.1rem; }
.profile-container .equity { font-family: monospace; font-size: 0.85rem; padding: 0.5rem;
  background: #f8fafc; border-radius: 4px; margin: 0.5rem 0; max-height: 200px; overflow-y: auto; }

footer { background: #0f172a; color: #94a3b8; padding: 1.5rem; text-align: center; font-size: 0.8rem; }
footer a { color: #93c5fd; }
footer .small { font-size: 0.7rem; margin-top: 0.5rem; opacity: 0.7; }

/* Responsive */
@media (max-width: 768px) {
  header h1 { font-size: 1rem; }
  nav a { font-size: 0.7rem; padding: 0.2rem 0.4rem; }
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  table { font-size: 0.75rem; }
  td, th { padding: 0.35rem; }
}
"""


def _build_js() -> str:
    return r"""
// NFL Parlay Competition - Client-side app
// Loads site_data JSON bundles, renders leaderboard, trades, profiles, verification

async function fetchJSON(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) return null;
    return await res.json();
  } catch(e) { return null; }
}

function fmt$(n) {
  if (n == null) return '-';
  const v = Number(n);
  return (v >= 0 ? '+' : '') + '$' + v.toFixed(2);
}
function fmtPct(n) {
  if (n == null) return '-';
  const v = Number(n);
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}
function fmtDate(s) {
  if (!s) return '-';
  try { return new Date(s).toLocaleString(); } catch(e) { return s; }
}
function fmtShort(s) {
  if (!s) return '-';
  try { return new Date(s).toLocaleDateString(); } catch(e) { return s; }
}
function cls$(n) { return n >= 0 ? 'positive' : 'negative'; }
function badge(status) {
  const s = (status || '').toLowerCase();
  return `<span class="badge badge-${s}">${status}</span>`;
}
// Settlement provenance: never let a simulated outcome look like a real one.
function provBadge(t) {
  const src = t.settlement_result_source;
  if (!src) return '';
  const map = {
    OFFICIAL: ['prov-official', 'OFFICIAL RESULT', 'Read from the settled Kalshi market result field'],
    SIMULATED: ['prov-simulated', 'SIMULATED SETTLEMENT', 'No official Kalshi result was stored: the outcome was drawn from the market-implied probability. Not a verified result.'],
    PARTIAL: ['prov-simulated', 'PARTLY SIMULATED', 'Some legs had official results; others were drawn from market-implied probability'],
    UNKNOWN: ['prov-unknown', 'PROVENANCE UNKNOWN', 'Settlement provenance was not recorded for this trade'],
  };
  const [cls, label, title] = map[src] || map.UNKNOWN;
  return ` <span class="badge ${cls}" title="${title}">${label}</span>`;
}
function provCell(t) {
  const src = t.settlement_result_source;
  if (!src) return '<span style="color:#94a3b8">-</span>';
  if (src === 'OFFICIAL') return '<span style="color:#16a34a">official</span>';
  if (src === 'UNKNOWN') return '<span style="color:#64748b">unknown</span>';
  return '<span style="color:#ca8a04">simulated</span>';
}
// Expandable full record so any trade can be audited field by field.
function tradeDetail(t) {
  const legs = (t.legs || []).map((l, i) => `
    <div class="leg">
      <div><strong>Leg ${i+1}</strong> — <code>${l.market_ticker || ''}</code></div>
      <div class="kv"><span>Event</span><span><code>${l.event_ticker || ''}</code></span></div>
      <div class="kv"><span>Series</span><span><code>${l.series_ticker || ''}</code></span></div>
      <div class="kv"><span>Side</span><span>${l.side || ''}</span></div>
      <div class="kv"><span>Entry price</span><span>${l.entry_price ?? '-'}</span></div>
      <div class="kv"><span>Exec price</span><span>${l.exec_price ?? '-'}</span></div>
      <div class="kv"><span>Quantity</span><span>${l.quantity ?? '-'}${l.quantity_requested != null && l.quantity_requested !== l.quantity ? ` (requested ${l.quantity_requested})` : ''}</span></div>
      <div class="kv"><span>Bid / Ask at entry</span><span>${l.bid_at_entry ?? '-'} / ${l.ask_at_entry ?? '-'}</span></div>
      <div class="kv"><span>Spread</span><span>${l.spread ?? '-'}</span></div>
      <div class="kv"><span>Implied prob</span><span>${l.implied_prob ?? '-'}</span></div>
      <div class="kv"><span>Liquidity at entry</span><span>${l.liquidity_at_entry ?? '-'}</span></div>
      <div class="kv"><span>Snapshot file</span><span><code>${l.source_file || ''}</code></span></div>
      <div class="kv"><span>Snapshot SHA-256</span><span><code>${l.source_sha256 || ''}</code></span></div>
      <div class="kv"><span>Entry timestamp</span><span>${l.entry_timestamp || ''}</span></div>
      <div class="kv"><span>Official source</span><span><a href="${l.source_url||'#'}" target="_blank">${l.source_url || ''}</a></span></div>
    </div>`).join('');
  const flags = (t.flags || []).map(f =>
    `<div class="mini-flag flag-${f.severity||'low'}"><strong>${f.flag_type}</strong> [${f.severity}] ${f.message}</div>`
  ).join('') || '<div style="color:#16a34a">No flags on this trade</div>';
  const sources = (t.official_sources || []).map(s =>
    `<div><a href="${s}" target="_blank">${s}</a></div>`).join('') || '<div>-</div>';
  return `
    <div class="detail">
      <h4>Trade record — ${t.trade_id || ''}</h4>
      <div class="kv"><span>Status</span><span>${t.status || ''}</span></div>
      <div class="kv"><span>Result</span><span>${t.result || ''}</span></div>
      <div class="kv"><span>Settlement source</span><span>${t.settlement_result_source || 'not recorded'}</span></div>
      ${t.settlement_note ? `<div class="kv"><span>Note</span><span>${t.settlement_note}</span></div>` : ''}
      <div class="kv"><span>Market type</span><span>${t.market_type || ''}</span></div>
      <div class="kv"><span>Created</span><span>${fmtDate(t.created_at)}</span></div>
      <div class="kv"><span>Updated</span><span>${fmtDate(t.updated_at)}</span></div>
      <div class="kv"><span>Why entered</span><span>${t.why_entered || ''}</span></div>
      <div class="kv"><span>Expected value</span><span>${t.expected_value ?? '-'}</span></div>
      <div class="kv"><span>Cost (price x contracts)</span><span>$${(t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Fees paid at entry</span><span>$${(t.fees ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Total debit</span><span>$${(t.total_debit_dollars ?? t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Payout at settlement</span><span>${t.payout_dollars != null ? '$' + Number(t.payout_dollars).toFixed(2) : '-'}</span></div>
      <div class="kv"><span>PnL</span><span class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</span></div>
      <div class="kv"><span>ROI</span><span class="${cls$(t.roi_percent)}">${t.roi_percent != null ? fmtPct(t.roi_percent) : '-'}</span></div>
      <div class="kv"><span>Fee model</span><span><code>${t.fee_model || 'not recorded'}</code></span></div>
      <h4>Legs (${(t.legs||[]).length})</h4>${legs}
      <h4>Official sources (verify here)</h4>${sources}
      <h4>Flags (${(t.flags||[]).length})</h4>${flags}
    </div>`;
}
// Pretty-print the arithmetic a reviewer would check by hand.
function reconcile(t) {
  if (t.pnl_dollars == null || t.position_size_dollars == null) return '';
  const payout = t.payout_dollars != null ? t.payout_dollars : (t.position_size_dollars + (t.fees||0) + t.pnl_dollars);
  const check = payout - t.position_size_dollars - (t.fees || 0);
  const ok = Math.abs(check - t.pnl_dollars) < 0.02;
  return `<div class="reconcile">
    <code>payout ${fmtMoneyPlain(payout)} - cost ${fmtMoneyPlain(t.position_size_dollars)} - fees ${fmtMoneyPlain(t.fees||0)} = ${fmtMoneyPlain(check)}</code>
    ${ok ? '<span class="ok">checkable: matches recorded PnL</span>' : '<span class="bad">MISMATCH vs recorded PnL ' + fmtMoneyPlain(t.pnl_dollars) + '</span>'}
  </div>`;
}
function fmtMoneyPlain(n) { return '$' + Number(n || 0).toFixed(2); }
function toggleDetail(tradeId) {
  const el = document.getElementById('detail-' + tradeId);
  if (el) el.classList.toggle('open');
}

// Navigation
let currentPage = 1;
let currentSearch = '';
let currentSort = 'rank';
let currentPageSize = 25;

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const section = link.dataset.section;
    if (!section) return;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const el = document.getElementById(section);
    if (el) el.classList.add('active');
    link.classList.add('active');
    if (section === 'leaderboard') loadLeaderboard();
  });
});

// Overview
async function loadOverview() {
  const data = await fetchJSON('site_data/competition.json');
  if (!data) { document.getElementById('overview-content').innerHTML = '<p>No competition data yet. Run simulate.py first.</p>'; return; }
  const top = data.top_performer;
  const worst = data.worst_performer;
  const statusCounts = data.by_status || {};
  const exec = (statusCounts.EXECUTED||0) + (statusCounts.SETTLED||0) + (statusCounts.CLOSED||0);

  document.getElementById('overview-content').innerHTML = `
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Season</div><div class="value">${data.season}</div></div>
      <div class="stat-card"><div class="label">Status</div><div class="value">${data.status}</div></div>
      <div class="stat-card"><div class="label">Users</div><div class="value">${data.total_users}</div></div>
      <div class="stat-card"><div class="label">Total Trades</div><div class="value">${data.total_trades}</div></div>
      <div class="stat-card"><div class="label">Total PnL</div><div class="value ${cls$(data.total_pnl)}">${fmt$(data.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">Avg ROI</div><div class="value ${cls$(data.avg_roi)}">${fmtPct(data.avg_roi)}</div></div>
    </div>
    <div class="card">
      <h3>Top Performer</h3>
      <p>${top ? `<strong>${top.username}</strong> — ${top.strategy_name}<br>PnL ${fmt$(top.total_pnl)} | ROI ${fmtPct(top.roi_percent)} | ${top.wins}W-${top.losses}L` : 'None'}</p>
    </div>
    <div class="card">
      <h3>Trade Activity</h3>
      <p>Executed: ${exec} | Pending: ${statusCounts.ORDER||0} | Rejected: ${statusCounts.REJECTED||0} | Settled: ${statusCounts.SETTLED||0}</p>
    </div>
    <div class="card">
      <h3>Scalability</h3>
      <p>Supports ${(data.scalability_test?.supported||[]).join(' → ')} users. Current: <strong>${data.scalability_test?.current}</strong>.</p>
      <p>${data.scalability_test?.architecture}</p>
    </div>
  `;
}

// Leaderboard
async function loadLeaderboard() {
  const data = await fetchJSON(`site_data/leaderboard_page_${currentPage}.json`);
  if (!data) {
    const all = await fetchJSON('site_data/leaderboard.json');
    if (!all) { document.getElementById('leaderboard-content').innerHTML = '<p>No users yet.</p>'; return; }
    renderLeaderboard(all.users, all.count, 1, 1);
    return;
  }
  renderLeaderboard(data.users, data.total, data.page, data.total_pages);
}

function renderLeaderboard(users, total, page, totalPages) {
  let filtered = users || [];
  if (currentSearch) {
    const s = currentSearch.toLowerCase();
    filtered = filtered.filter(u =>
      (u.username||'').toLowerCase().includes(s) ||
      (u.strategy_name||'').toLowerCase().includes(s));
  }

  const sortFns = {
    pnl: (a,b) => b.total_pnl - a.total_pnl,
    roi: (a,b) => b.roi_percent - a.roi_percent,
    win_rate: (a,b) => b.win_rate - a.win_rate,
    trades: (a,b) => b.total_trades - a.total_trades,
    bankroll: (a,b) => b.current_bankroll - a.current_bankroll,
    rank: (a,b) => (a.rank||9999) - (b.rank||9999),
  };
  if (sortFns[currentSort]) filtered = [...filtered].sort(sortFns[currentSort]);

  const slice = filtered.slice(0, currentPageSize);
  let html = `<div class="table-container"><table>
    <thead><tr>
      <th>#</th><th>Username</th><th>Strategy</th><th>Bankroll</th>
      <th>PnL</th><th>ROI</th><th>W-L</th><th>Win%</th>
      <th>Trades</th><th>Open</th><th>Last Trade</th>
    </tr></thead><tbody>`;

  for (const u of slice) {
    html += `<tr>
      <td>${u.rank || '-'}</td>
      <td><a href="#" onclick="loadProfile('${u.user_id}');return false;" title="${u.strategy_description||''}">${u.username}</a></td>
      <td title="${u.strategy_description||''}">${(u.strategy_name||'').slice(0,30)}</td>
      <td>$${Number(u.current_bankroll||0).toFixed(0)}</td>
      <td class="${cls$(u.total_pnl)}">${fmt$(u.total_pnl)}</td>
      <td class="${cls$(u.roi_percent)}">${fmtPct(u.roi_percent)}</td>
      <td>${u.wins||0}-${u.losses||0}</td>
      <td>${u.win_rate||0}%</td>
      <td>${u.total_trades||0}</td>
      <td>${(u.open_trades||[]).length}</td>
      <td>${fmtShort(u.last_trade_at)}</td>
    </tr>`;
  }
  html += '</tbody></table></div>';
  document.getElementById('leaderboard-content').innerHTML = html;

  // Pagination
  const tp = Math.ceil(total / currentPageSize) || 1;
  let pag = `<span style="margin-right:0.5rem;font-size:0.8rem;color:#64748b">${total} users</span>`;
  for (let i = 1; i <= Math.min(tp, 15); i++) {
    pag += `<button class="${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
  }
  if (tp > 15) pag += `<span>...</span><button onclick="goPage(${tp})">${tp}</button>`;
  document.getElementById('pagination').innerHTML = pag;
}

function goPage(p) { currentPage = p; loadLeaderboard(); }

// User Profile — the profile summary is per-user, but trade bodies come from the
// single shared index, filtered client-side by user_id.
let tradeIndexCache = null;
async function getTradeIndex() {
  if (tradeIndexCache) return tradeIndexCache;
  const data = await fetchJSON('site_data/trades/index.json');
  tradeIndexCache = data ? (data.trades || []) : [];
  return tradeIndexCache;
}
// Expand the compact leg keys back to readable names for display.
function expandLeg(l) {
  if (l.market_ticker) return l;   // already a full record
  return {
    market_ticker: l.t, event_ticker: l.e, series_ticker: l.s,
    side: l.side, entry_price: l.px, exec_price: l.exec,
    quantity: l.qty, quantity_requested: l.qty_req,
    bid_at_entry: l.bid, ask_at_entry: l.ask, spread: l.spr,
    implied_prob: l.ip, liquidity_at_entry: l.liq,
    reason: l.req, model_prob: l.mp, source_file: l.src, source_sha256: l.sha,
    entry_timestamp: l.ts, source_url: l.u, verification_url: l.v,
  };
}
function expandTrade(t) {
  if (!t || !t.legs) return t;
  return { ...t, legs: t.legs.map(expandLeg) };
}

let strategyCache = null;
async function getStrategies() {
  if (strategyCache) return strategyCache;
  const data = await fetchJSON('site_data/strategies.json');
  strategyCache = {};
  for (const s of ((data && data.strategies) || [])) strategyCache[s.strategy_id] = s;
  return strategyCache;
}

async function loadProfile(userId) {
  const data = await fetchJSON(`site_data/users/${userId}.json`);
  if (!data) { document.getElementById('user-profile').innerHTML = '<p>User not found.</p>'; return; }
  const index = await getTradeIndex();
  const mine = index.filter(t => t.user_id === userId).map(expandTrade);
  data.trades = mine;
  // Strategy text is served once from the strategy library, not per user.
  const strategy = (await getStrategies())[data.strategy_ref] || {};
  const u = data.user;
  const s = data.stats;

  let html = `
    <div class="card">
      <h3>${u.username} — ${u.strategy_name}</h3>
      <p class="subtitle">${u.strategy_description || ''}</p>
      <div class="kv"><div>Category</div><div>${strategy.category || '-'}</div></div>
      <details><summary>Full Strategy Explanation</summary>
        <pre style="white-space:pre-wrap;margin-top:0.5rem">${strategy.long_explanation || 'not available'}</pre>
      </details>
      <details><summary>Strategy sources (${(strategy.sources||[]).length})</summary>
        ${(strategy.sources||[]).map(src => `<div><a href="${src}" target="_blank">${src}</a></div>`).join('')}
      </details>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Starting Bankroll</div><div class="value">$${Number(u.starting_bankroll).toFixed(0)}</div></div>
      <div class="stat-card"><div class="label">Current Bankroll</div><div class="value ${cls$(u.current_bankroll - u.starting_bankroll)}">$${Number(u.current_bankroll).toFixed(0)}</div></div>
      <div class="stat-card"><div class="label">Total PnL</div><div class="value ${cls$(u.total_pnl)}">${fmt$(u.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">ROI</div><div class="value ${cls$(u.roi_percent)}">${fmtPct(u.roi_percent)}</div></div>
      <div class="stat-card"><div class="label">Rank</div><div class="value">#${u.rank || '-'}</div></div>
      <div class="stat-card"><div class="label">Win Rate</div><div class="value">${u.win_rate || 0}%</div></div>
      <div class="stat-card"><div class="label">Trades</div><div class="value">${u.total_trades || 0}</div></div>
      <div class="stat-card"><div class="label">Open Exposure</div><div class="value">$${(s.open_exposure||0).toFixed(2)}</div></div>
    </div>
    <div class="card"><h3>Performance</h3>
      <div class="stat-grid">
        <div class="stat-card"><div class="label">Wins / Losses</div><div class="value">${s.wins} / ${s.losses}</div></div>
        <div class="stat-card"><div class="label">Max Drawdown</div><div class="value">${s.max_drawdown_pct ?? 0}%</div></div>
        <div class="stat-card"><div class="label">Gross Profit</div><div class="value positive">${fmt$(s.gross_profit)}</div></div>
        <div class="stat-card"><div class="label">Gross Loss</div><div class="value negative">${fmt$(s.gross_loss)}</div></div>
        <div class="stat-card"><div class="label">Total Fees Paid</div><div class="value">$${(s.total_fees||0).toFixed(2)}</div></div>
        <div class="stat-card"><div class="label">Total Volume</div><div class="value">$${(s.total_volume||0).toFixed(2)}</div></div>
        <div class="stat-card"><div class="label">Avg PnL / Trade</div><div class="value ${cls$(s.avg_trade_pnl)}">${fmt$(s.avg_trade_pnl)}</div></div>
        <div class="stat-card"><div class="label">Avg ROI / Trade</div><div class="value ${cls$(s.avg_roi_per_trade)}">${fmtPct(s.avg_roi_per_trade)}</div></div>
        <div class="stat-card"><div class="label">Open / Closed</div><div class="value">${s.open_positions} / ${s.closed_positions}</div></div>
      </div>
      <p class="subtitle">Settlement provenance:
        ${Object.entries(s.settlement_sources || {}).filter(([,v]) => v)
          .map(([k,v]) => `${k} ${v}`).join(' · ') || 'no settled trades yet'}
        — a SIMULATED outcome is a draw from the market-implied probability, not a verified result.</p>
    </div>`;

  // Equity curve: a simple inline sparkline over the stored history.
  const eq = data.equity_curve || [];
  if (eq.length > 0) {
    const values = eq.map(p => Number(p.bankroll));
    const lo = Math.min(...values), hi = Math.max(...values);
    const span = (hi - lo) || 1;
    const pts = values.map((v, i) => {
      const x = values.length === 1 ? 100 : (i / (values.length - 1)) * 100;
      const y = 30 - ((v - lo) / span) * 28;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(' ');
    html += `<div class="card"><h3>Equity Curve (${eq.length} points)</h3>
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" class="spark">
        <polyline points="${pts}" fill="none" stroke="#1e40af" stroke-width="0.6"/>
      </svg>
      <div class="kv"><span>High</span><span>$${hi.toFixed(2)}</span></div>
      <div class="kv"><span>Low</span><span>$${lo.toFixed(2)}</span></div>
      <div class="kv"><span>Latest</span><span>$${values[values.length-1].toFixed(2)}</span></div>
      <details><summary>Full history</summary><div class="equity">`;
    for (const pt of eq.slice(-50)) {
      html += `${fmtDate(pt.t)}: $${Number(pt.bankroll).toFixed(2)} (PnL: ${fmt$(pt.pnl)})<br>`;
    }
    html += '</div></details></div>';
  }

  // Trade history with drill-down
  const trades = data.trades || [];
  html += `<div class="card"><h3>Trade History (${trades.length})</h3>
    <p class="subtitle">Click any row to inspect the full record: every leg, every price,
    the snapshot file, the fee model, and the official source link.</p>`;
  if (trades.length === 0) {
    html += '<p>No trades yet.</p>';
  } else {
    html += `<div class="table-container"><table>
      <thead><tr><th>ID</th><th>Legs</th><th>Entry</th><th>Exit</th><th>Cost</th>
      <th>Fees</th><th>PnL</th><th>ROI</th><th>Status</th><th>Settlement</th></tr></thead><tbody>`;
    for (const t of trades.slice(0, 50)) {
      const legs = (t.legs || []).map(l =>
        `${(l.market_ticker||'').slice(0,30)} ${l.side}@${l.entry_price}`
      ).join('<br>');
      const tid = t.trade_id || '';
      html += `<tr class="clickable" onclick="toggleDetail('${tid}')">
        <td title="${tid}">${tid.slice(0, 12)} ▸</td>
        <td style="font-size:0.75rem">${legs}</td>
        <td>${t.entry_price_combined || '-'}</td>
        <td>${t.exit_price_combined ?? t.settlement_price ?? '-'}</td>
        <td>$${(t.position_size_dollars || 0).toFixed(2)}</td>
        <td>$${(t.fees || 0).toFixed(2)}</td>
        <td class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</td>
        <td class="${cls$(t.roi_percent)}">${t.roi_percent != null ? fmtPct(t.roi_percent) : '-'}</td>
        <td>${badge(t.status)}</td>
        <td>${provCell(t)}</td>
      </tr>
      <tr class="detail-row" id="detail-${tid}"><td colspan="10">
        ${tradeDetail(t)}${reconcile(t)}
      </td></tr>`;
    }
    html += '</tbody></table></div>';
  }
  html += '</div>';
  document.getElementById('user-profile').innerHTML = html;
  // Switch to users section
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('users').classList.add('active');
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  document.querySelector('[data-section="users"]').classList.add('active');
  document.getElementById('user-profile').scrollIntoView({ behavior: 'smooth' });
}

// Trades (upcoming/recent)
async function loadTrades(sectionId, fileName) {
  const data = await fetchJSON(`site_data/trades/${fileName}`);
  if (!data) { document.getElementById(sectionId).innerHTML = '<p>No trades.</p>'; return; }
  const trades = data.trades || [];
  if (trades.length === 0) {
    document.getElementById(sectionId).innerHTML = `<p>No ${fileName.replace('.json','')} trades yet.</p>`;
    return;
  }
  let html = `<p class="subtitle">Showing ${Math.min(trades.length, 50)} of ${data.count} trades
    — click a row for the full verifiable record</p>`;
  html += `<div class="table-container"><table>
    <thead><tr><th>ID</th><th>User</th><th>Strategy</th><th>Legs</th><th>Entry</th>
    <th>Cost</th><th>Fees</th><th>PnL</th><th>Status</th><th>Created</th></tr></thead><tbody>`;
  for (const t of trades.slice(0, 50)) {
    const legs = (t.legs || []).map(l =>
      `${(l.market_ticker||'').slice(0,25)} ${l.side}@${l.entry_price}`
    ).join('<br>');
    const tid = t.trade_id || '';
    html += `<tr class="clickable" onclick="toggleDetail('${tid}')">
      <td title="${tid}">${tid.slice(0, 12)} ▸</td>
      <td><a href="#" onclick="loadProfile('${t.user_id}');return false;">${t.username}</a></td>
      <td>${(t.strategy_id||'').replace('STRAT_','').slice(0,20)}</td>
      <td style="font-size:0.75rem">${legs}</td>
      <td>${t.entry_price_combined || '-'}</td>
      <td>$${(t.position_size_dollars || 0).toFixed(2)}</td>
      <td>$${(t.fees || 0).toFixed(2)}</td>
      <td class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</td>
      <td>${badge(t.status)}${provBadge(t)}</td>
      <td>${fmtShort(t.created_at)}</td>
    </tr>
    <tr class="detail-row" id="detail-${tid}"><td colspan="10">
      ${tradeDetail(t)}${reconcile(t)}
    </td></tr>`;
  }
  html += '</tbody></table></div>';
  document.getElementById(sectionId).innerHTML = html;
}

// Markets
async function loadMarkets() {
  const data = await fetchJSON('site_data/markets.json');
  if (!data) { document.getElementById('markets-content').innerHTML = '<p>No market data.</p>'; return; }
  let html = `<p class="subtitle">Events: ${(data.events||[]).length} | Markets: ${(data.markets||[]).length}</p>`;
  if ((data.markets||[]).length === 0) {
    html += '<p>No market snapshots. Run collect.py to fetch real Kalshi data.</p>';
  } else {
    html += `<div class="table-container"><table>
      <thead><tr><th>Ticker</th><th>Event</th><th>Series</th><th>Status</th>
      <th>Bid/Ask</th><th>Last</th><th>Volume</th><th>Verify</th></tr></thead><tbody>`;
    for (const m of (data.markets||[]).slice(0, 80)) {
      html += `<tr>
        <td title="${m.ticker}">${(m.ticker||'').slice(0,35)}</td>
        <td>${(m.event_ticker||'').slice(0,30)}</td>
        <td>${m.series_ticker}</td>
        <td>${badge(m.status)}</td>
        <td>${m.yes_bid||'-'}/${m.yes_ask||'-'}</td>
        <td>${m.last_price||'-'}</td>
        <td>${m.volume ? Number(m.volume).toFixed(0) : '-'}</td>
        <td><a href="https://kalshi.com/markets/${m.ticker}" target="_blank">Kalshi</a>
            <a href="https://api.elections.kalshi.com/trade-api/v2/markets/${m.ticker}" target="_blank">API</a></td>
      </tr>`;
    }
    html += '</tbody></table></div>';
  }
  document.getElementById('markets-content').innerHTML = html;
}

// Strategies
async function loadStrategies() {
  const data = await fetchJSON('site_data/strategies.json');
  if (!data) { document.getElementById('strategies-content').innerHTML = '<p>No strategies.</p>'; return; }
  let html = `<p class="subtitle">${data.count} distinct strategies across 5 categories</p>`;
  // Group by category
  const byCategory = {};
  for (const s of (data.strategies || [])) {
    const cat = s.category || 'Other';
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(s);
  }
  for (const [cat, strats] of Object.entries(byCategory)) {
    html += `<h3 style="margin:1rem 0 0.5rem;font-size:0.95rem;color:#475569">${cat} (${strats.length})</h3>`;
    for (const s of strats) {
      html += `<div class="card">
        <strong>${s.name}</strong> <span style="color:#64748b;font-size:0.75rem">${s.strategy_id}</span><br>
        <em style="font-size:0.85rem">${s.description}</em>
        <details style="margin-top:0.5rem"><summary>Full explanation</summary>
          <pre style="white-space:pre-wrap;font-size:0.78rem">${s.long_explanation || ''}</pre>
        </details>
        <div style="margin-top:0.5rem;font-size:0.8rem;color:#475569">
          Users: ${s.performance.users} | PnL: ${fmt$(s.performance.total_pnl)} | Avg ROI: ${fmtPct(s.performance.avg_roi)} | Trades: ${s.performance.trades}
        </div>
        <div style="font-size:0.75rem;color:#94a3b8">Sources: ${(s.sources||[]).join(', ')}</div>
      </div>`;
    }
  }
  document.getElementById('strategies-content').innerHTML = html;
}

// Verification
async function loadVerification() {
  const data = await fetchJSON('site_data/verification.json');
  if (!data) { document.getElementById('verification-content').innerHTML = '<p>No verification data.</p>'; return; }
  let html = `<div class="stat-grid">
    <div class="stat-card"><div class="label">Chain Valid</div><div class="value">${data.chain?.valid ? '✅' : '❌'}</div></div>
    <div class="stat-card"><div class="label">Chain Count</div><div class="value">${data.chain?.count || 0}</div></div>
    <div class="stat-card"><div class="label">Manifest Rows</div><div class="value">${data.manifest?.rows || 0}</div></div>
    <div class="stat-card"><div class="label">Total Trades</div><div class="value">${data.trades?.total_trades || 0}</div></div>
    <div class="stat-card"><div class="label">Errors</div><div class="value">${(data.trades?.errors||[]).length}</div></div>
    <div class="stat-card"><div class="label">Flags</div><div class="value">${(data.trades?.flags||[]).length}</div></div>
  </div>`;

  const agg = data.trades?.flags_aggregated || [];
  const totalFlags = data.trades?.flags_total ?? (data.trades?.flags || []).length;
  if (agg.length > 0) {
    html += `<h3>Flags by type (${totalFlags} total)</h3>
      <p class="subtitle">Aggregated so the page stays readable at 1,000 users. The
      complete per-trade flag list lives in the ledger and in
      data/competition/verification_report.json.</p>
      <div class="table-container"><table>
      <thead><tr><th>Flag type</th><th>Severity</th><th>Occurrences</th>
      <th>Trades affected</th><th>Example</th></tr></thead><tbody>`;
    for (const f of agg) {
      html += `<tr class="flag-${f.severity||'low'}">
        <td><strong>${f.flag_type}</strong></td>
        <td>${f.severity || '-'}</td>
        <td>${f.count}</td>
        <td>${f.trades_affected}</td>
        <td style="font-size:0.75rem">${(f.sample_messages||[])[0] || ''}</td>
      </tr>`;
    }
    html += '</tbody></table></div>';
  }

  const sample = data.trades?.flags || [];
  if (sample.length > 0) {
    html += `<details><summary>Sample of individual flags (${sample.length} shown${data.trades.flags_truncated ? ', truncated' : ''})</summary>`;
    for (const f of sample) {
      html += `<div class="card flag-${f.severity||'low'}" style="margin-top:0.5rem">
        <strong>${f.flag_type}</strong> [${f.severity}] ${f.message}
        ${f.trade_id ? `<br><small>Trade: ${f.trade_id}</small>` : ''}
      </div>`;
    }
    html += '</details>';
  }

  const errs = data.trades?.errors || [];
  if (errs.length > 0) {
    html += `<h3>Errors (${errs.length})</h3>`;
    for (const e of errs.slice(0, 20)) {
      html += `<div class="card flag-high"><strong>${e.trade_id || ''}</strong> ${e.error}</div>`;
    }
  }
  document.getElementById('verification-content').innerHTML = html;

  const sources = await fetchJSON('site_data/data_sources.json');
  if (sources) {
    let shtml = '<div class="card"><h3>Data Sources</h3><pre style="white-space:pre-wrap">';
    shtml += JSON.stringify(sources.sources, null, 2);
    shtml += '</pre></div>';
    document.getElementById('data-sources-content').innerHTML = shtml;
  }
}

// History
async function loadHistory() {
  const data = await fetchJSON('site_data/competition.json');
  const scale = data?.scalability_test || {};
  document.getElementById('history-content').innerHTML = `
    <div class="card">
      <h3>Architecture</h3>
      <p>Shared market data in <code>data/raw/kalshi/</code> (loaded once, not duplicated per user).</p>
      <p>Hash-chained ledger <code>data/competition/ledger.jsonl</code> — append-only, SHA-256 chain.</p>
      <p>Lightweight <code>users.json</code> with performance history.</p>
      <p>Pre-aggregated <code>site_data/</code> JSON for fast page loads.</p>
    </div>
    <div class="card">
      <h3>Scalability Test</h3>
      <p>Supports: ${(scale.supported||[]).join(' → ')} users</p>
      <p>Current: <strong>${scale.current || 0}</strong> users</p>
      <p>Method: <code>${scale.architecture}</code></p>
    </div>
    <div class="card">
      <h3>Data Model</h3>
      <p><strong>Real verified data:</strong> Kalshi Trade API v2 (read-only, no credentials), ESPN keyless, NWS. Every fetch logged to manifest with SHA-256.</p>
      <p><strong>Simulated trades:</strong> Paper trades executed against real market data. Clearly labeled as SIMULATED.</p>
      <p><strong>Parlay model:</strong> Synthetic parlay (portfolio of independent markets, flagged with correlation warning) vs Native COMBO (KXNFLCOMBO, RFQ-priced).</p>
      <p><strong>Verification path:</strong> Leaderboard → User → Trade → Official Source (API link + Kalshi page).</p>
    </div>
    <div class="card">
      <h3>Paper Trading Realism</h3>
      <p>Bid/ask spread, liquidity checks (10% depth rule), slippage (bps), fees (7% profit), market status checks, orderbook when available.</p>
    </div>
  `;
}

// Event listeners
document.getElementById('search').addEventListener('input', e => {
  currentSearch = e.target.value; currentPage = 1; loadLeaderboard();
});
document.getElementById('sort').addEventListener('change', e => {
  currentSort = e.target.value; loadLeaderboard();
});
document.getElementById('pageSize').addEventListener('change', e => {
  currentPageSize = parseInt(e.target.value); currentPage = 1; loadLeaderboard();
});

// Init
loadOverview();
loadLeaderboard();
loadTrades('upcoming-content', 'upcoming.json');
loadTrades('recent-content', 'recent.json');
loadMarkets();
loadStrategies();
loadVerification();
loadHistory();
"""


def remove_legacy_root_bundle():
    """Delete the pre-1.0 duplicate bundle at the repository root, if present.

    Bundles used to be written to <root>/site_data and copied into docs/site_data,
    which committed every byte twice.
    """
    legacy = os.path.join(ROOT, "site_data")
    if os.path.isdir(legacy):
        shutil.rmtree(legacy)
        return True
    return False

def main() -> int:
    if remove_legacy_root_bundle():
        print("Removed legacy duplicate bundle at <root>/site_data")
    ensure_dirs()
    print("Building site data...")
    build_leaderboard()
    print(" - leaderboard")
    build_user_profiles()
    print(" - user profiles")
    build_trades()
    print(" - trades")
    build_markets()
    print(" - markets")
    build_strategies()
    print(" - strategies")
    build_verification()
    print(" - verification")
    build_competition_overview()
    print(" - competition overview")
    build_docs_site()
    print(" - docs site")
    # .nojekyll stops GitHub Pages running Jekyll, which would otherwise skip files
    # and directories beginning with an underscore.
    with open(os.path.join(DOCS, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")
    print(f"Done — bundles written to {os.path.relpath(SITE_DATA, ROOT)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
