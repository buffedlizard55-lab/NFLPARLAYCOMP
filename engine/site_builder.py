#!/usr/bin/env python3
"""
Site builder: generates static JSON bundles for GitHub Pages site.

Enhanced for full competition requirements:
- Competition (Overview, Leaderboard, Upcoming Trades, Recent Trades, Markets)
- Strategies (Library, Performance, Research)
- Users (Search, Profiles, Trade History)
- Verification (Trade Verification, Data Sources, Data Integrity/Flags)
- History (Previous Competitions, Scalability, Architecture)

Outputs to docs/site_data (GitHub Pages serves docs/)
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
SITE_DATA = os.path.join(DOCS, "site_data")
COMP = os.path.join(ROOT, "data", "competition")
RAW = os.path.join(ROOT, "data", "raw")

def _fresh_dir(path: str) -> str:
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)
    return path

def ensure_dirs():
    os.makedirs(DOCS, exist_ok=True)
    _fresh_dir(SITE_DATA)
    _fresh_dir(os.path.join(SITE_DATA, "users"))
    _fresh_dir(os.path.join(SITE_DATA, "trades"))

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

def _compact_leg(leg: dict) -> dict:
    return {
        "t": leg.get("market_ticker"),
        "e": leg.get("event_ticker"),
        "s": leg.get("series_ticker"),
        "contract": leg.get("contract") or leg.get("market_ticker"),
        "side": leg.get("side"),
        "px": leg.get("entry_price"),
        "exec": leg.get("exec_price"),
        "qty": leg.get("quantity"),
        "qty_req": leg.get("quantity_requested"),
        "bid": leg.get("bid_at_entry") or leg.get("bid"),
        "ask": leg.get("ask_at_entry") or leg.get("ask"),
        "spr": leg.get("spread"),
        "ip": leg.get("implied_prob"),
        "liq": leg.get("liquidity_at_entry") or leg.get("liquidity"),
        "req": leg.get("reason"),
        "mp": leg.get("model_prob"),
        "src": leg.get("source_file"),
        "sha": leg.get("source_sha256"),
        "ts": leg.get("entry_timestamp"),
        "u": leg.get("source_url") or leg.get("official_source"),
        "v": leg.get("verification_url"),
        "exp": leg.get("expiration_date") or leg.get("close_time"),
        "pos_size": leg.get("position_size"),
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
        "proposed_entry_price": t.get("proposed_entry_price"),
        "current_verified_price": t.get("current_verified_price"),
        "is_executable": t.get("is_executable"),
        "required_liquidity": t.get("required_liquidity"),
        "conditions_required": t.get("conditions_required"),
        "invalidation_conditions": t.get("invalidation_conditions"),
    }

def build_leaderboard():
    users = load_users()
    sorted_users = sorted(users, key=lambda u: u.get("rank", 9999))
    rows = [_leaderboard_row(u) for u in sorted_users]
    with open(os.path.join(SITE_DATA, "leaderboard.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(rows), "users": rows}, f)

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

        # Trade frequency: trades per day
        trade_freq = 0
        if equity and len(equity) > 1:
            try:
                from datetime import datetime
                first = datetime.fromisoformat(equity[0]["t"].replace("Z", "+00:00"))
                last = datetime.fromisoformat(equity[-1]["t"].replace("Z", "+00:00"))
                days = max(1, (last - first).days + 1)
                trade_freq = len(settled) / days
            except:
                trade_freq = len(settled)

        # Win/loss distribution
        pnl_dist = {
            "wins": [t["pnl_dollars"] for t in settled if t.get("result") == "WIN"],
            "losses": [t["pnl_dollars"] for t in settled if t.get("result") == "LOSS"],
        }

        # ROI over time
        roi_history = []
        for point in equity:
            try:
                roi = ((point["bankroll"] - user["starting_bankroll"]) / user["starting_bankroll"]) * 100 if user["starting_bankroll"] else 0
                roi_history.append({"t": point["t"], "roi": round(roi, 2), "bankroll": point["bankroll"]})
            except:
                continue

        user_summary = {k: v for k, v in user.items()
                        if k not in ("strategy_long_explanation", "performance_history")}

        profile = {
            "user": user_summary,
            "strategy_ref": user.get("strategy_id"),
            "strategy_long_explanation_from": "site_data/strategies.json",
            "equity_curve": equity,
            "roi_history": roi_history,
            "pnl_distribution": pnl_dist,
            "trade_frequency": round(trade_freq, 3),
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
                "open_exposure": round(sum(t.get("position_size_dollars") or 0 for t in open_trades), 2),
                "total_volume": round(sum(t.get("position_size_dollars") or 0 for t in user_trades), 2),
                "total_fees": round(sum(t.get("fees") or 0 for t in user_trades), 2),
                "max_drawdown_pct": round(max_dd * 100, 2),
                "gross_profit": round(gross_win, 2),
                "gross_loss": round(gross_loss, 2),
                "avg_trade_pnl": round(user.get("total_pnl", 0) / len(settled), 2) if settled else 0.0,
                "avg_roi_per_trade": round(sum(t.get("roi_percent") or 0 for t in settled) / len(settled), 2) if settled else 0.0,
                "trade_frequency_per_day": round(trade_freq, 3),
                "settlement_sources": {
                    src: sum(1 for t in settled if t.get("settlement_result_source") == src)
                    for src in ("OFFICIAL", "SIMULATED", "PARTIAL", "UNKNOWN")
                },
            },
            "note": "Trade records from shared bundle site_data/trades/index.json, filtered by user_id",
            "updated_at": iso_now(),
        }
        with open(os.path.join(SITE_DATA, "users", f"{uid}.json"), "w", encoding="utf-8") as f:
            json.dump(profile, f)

def build_trades():
    trades = latest_trades()
    raw_entries = read_ledger()
    sorted_trades = sorted(trades, key=lambda x: x.get("created_at", ""), reverse=True)

    recent = sorted_trades[:200]
    upcoming = [t for t in sorted_trades if t.get("status") in ("CANDIDATE", "SIGNAL", "ORDER", "EXECUTED")][:200]
    closed = [t for t in sorted_trades if t.get("status") in ("SETTLED", "CLOSED")][:200]
    rejected = [t for t in sorted_trades if t.get("status") == "REJECTED"][:200]

    for name, data in [("recent", recent), ("upcoming", upcoming), ("closed", closed), ("rejected", rejected)]:
        with open(os.path.join(SITE_DATA, "trades", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump({"updated_at": iso_now(), "count": len(data), "trades": data}, f)

    candidates_path = os.path.join(COMP, "upcoming_candidates.json")
    if os.path.exists(candidates_path):
        try:
            with open(candidates_path, "r", encoding="utf-8") as cf:
                cand_data = json.load(cf)
                candidates = cand_data.get("candidates", [])
        except:
            candidates = []
    else:
        candidates = []

    with open(os.path.join(SITE_DATA, "trades", "candidates.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(candidates), "trades": candidates[:200], "candidates": candidates[:200]}, f)

    combined_upcoming = candidates[:100] + upcoming[:100]
    with open(os.path.join(SITE_DATA, "trades", "upcoming_combined.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(combined_upcoming), "trades": combined_upcoming, "candidates": candidates[:100], "executed": upcoming[:100]}, f)

    index_rows = [_compact_trade(t) for t in sorted_trades]
    with open(os.path.join(SITE_DATA, "trades", "index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": iso_now(),
            "count": len(index_rows),
            "field_map": {
                "t": "market_ticker", "e": "event_ticker", "s": "series_ticker",
                "contract": "contract", "px": "entry_price", "exec": "executed price",
                "qty": "quantity filled", "qty_req": "quantity requested",
                "bid": "bid at entry", "ask": "ask at entry", "spr": "quoted spread",
                "ip": "implied probability", "liq": "liquidity at entry",
                "req": "strategy reason", "mp": "model probability",
                "src": "snapshot file", "sha": "snapshot sha256",
                "ts": "entry timestamp", "u": "official source url", "v": "verification url",
                "exp": "expiration/settlement date", "pos_size": "position size",
            },
            "trades": index_rows,
        }, f)

    statuses = ["CANDIDATE", "SIGNAL", "ORDER", "EXECUTED", "CLOSED", "SETTLED", "CANCELLED", "REJECTED"]
    with open(os.path.join(SITE_DATA, "trades", "ledger_summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": iso_now(),
            "total": len(trades),
            "ledger_entries": len(raw_entries),
            "by_status": {s: len([t for t in trades if t.get("status") == s]) for s in statuses},
            "note": "`total` distinct trades, `ledger_entries` includes full audit trail",
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
    else:
        # synthetic fixture note
        markets_data["note"] = "No verified Kalshi snapshots — running on synthetic fixtures flagged UNVERIFIED_DATA"

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

    # Strategy research documentation
    research = {
        "updated_at": iso_now(),
        "discovery_sources": [
            {"source": "Academic: Wolfers & Zitzewitz 2004 Prediction Markets", "url": "https://www.aeaweb.org/articles?id=10.1257/0895330041371321", "use": "Market efficiency framing, not price"},
            {"source": "Reddit r/sportsbook", "url": "https://reddit.com/r/sportsbook", "use": "Strategy discovery only — public fade, weather, rest concepts"},
            {"source": "Reddit r/nfl", "url": "https://reddit.com/r/nfl", "use": "Team performance, injury impact discussion"},
            {"source": "ESPN NFL APIs", "url": "https://site.api.espn.com/apis/site/v2/sports/football/nfl", "use": "NFL metadata only — schedule, venue, injuries, not price"},
            {"source": "NWS api.weather.gov", "url": "https://api.weather.gov", "use": "Weather forecasts forward-only"},
            {"source": "Kalshi Docs", "url": "https://docs.kalshi.com/", "use": "Official market structure, orderbook, candlesticks"},
            {"source": "Kalshi Fee Schedule", "url": "https://kalshi.com/docs/kalshi-fee-schedule.pdf", "use": "Fee model transcription, asserted by tests"},
        ],
        "strategy_categories": {
            "MARKET_BASED": "Uses price, volume, spread, orderbook, candlesticks to find mispricing or momentum",
            "GAME_BASED": "Uses game-specific info like home/away, spread, totals, team quality",
            "SITUATIONAL": "Uses situational factors like weather, injuries, rest, travel, indoor/outdoor",
            "STATISTICAL": "Uses statistical models like Elo, DVOA, mean reversion, streaks",
            "CORRELATION": "Uses correlation between markets for parlay construction",
            "PROP_BASED": "Uses prop markets like TD scorers, win margin, specials, quarter winners",
        },
        "research_notes": "All strategies are documented as hypotheses, not proven edges. Many are falsification targets where premise does not match implementation — documented explicitly. No third-party performance figure is repeated without verification.",
    }
    with open(os.path.join(SITE_DATA, "strategy_research.json"), "w", encoding="utf-8") as f:
        json.dump(research, f)

def build_verification():
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
            "note": "Only official Kalshi Trade API v2, read-only, no credentials",
            "data_class": "Real verified market data when data/raw/kalshi present, flagged synthetic otherwise",
        },
        "espn_api": {
            "base_url": "https://site.api.espn.com/apis/site/v2/sports/football/nfl",
            "endpoints": ["/scoreboard", "/injuries"],
            "note": "NFL metadata only — not price source",
            "data_class": "Real public data",
        },
        "nws_api": {
            "base_url": "https://api.weather.gov",
            "note": "Weather forecasts forward-only, historical unavailable",
            "data_class": "Real public data, forward-only",
        },
        "simulated": {
            "note": "All trades, fills, PnL, bankrolls, rankings are SIMULATED paper trading",
            "distinction": "Real verified data and simulated activity never blended",
        },
        "master_site_projects": {
            "NFL Injury Report": "https://buffedlizard55-lab.github.io/NFLInjuryReport/ — cross-check injury data",
            "NFLComp": "https://buffedlizard55-lab.github.io/NFLComp/ — strategy discovery reference",
            "Commodities": "https://buffedlizard55-lab.github.io/Commodities/ — ledger design reference",
            "NFL Scoreboard": "https://buffedlizard55-lab.github.io/NFLScoreboard/ or similar — schedule verification",
            "Weather": "Weather project — forecast cross-check",
        }
    }
    with open(os.path.join(SITE_DATA, "data_sources.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "sources": sources}, f)

def build_competition_overview():
    users = load_users()
    entries = read_ledger()
    trades = latest_trades(entries)
    total_pnl = sum(u.get("total_pnl", 0) for u in users)

    # Scalability test data
    scalability_levels = [5, 10, 15, 25, 30, 50, 70, 100, 250, 500, 750, 1000]

    overview = {
        "updated_at": iso_now(),
        "season": "2026",
        "status": "ACTIVE",
        "competition_period": "One NFL season / competition year (2026-09 to 2027-02)",
        "total_users": len(users),
        "total_trades": len(trades),
        "ledger_entries": len(entries),
        "data_provenance": {
            "real_kalshi_data_present": os.path.exists(os.path.join(RAW, "kalshi", "season_events.json")),
            "note": ("Raw verified Kalshi snapshots found in data/raw; prices trace to fetch manifest.")
            if os.path.exists(os.path.join(RAW, "kalshi", "season_events.json")) else
            ("NO verified Kalshi snapshots in data/raw — running on flagged synthetic fixtures for offline/scalability testing. All trades carry UNVERIFIED_DATA flag until collection succeeds."),
        },
        "total_pnl": round(total_pnl, 2),
        "avg_roi": round(sum(u.get("roi_percent", 0) for u in users) / max(1, len(users)), 2),
        "top_performer": sorted(users, key=lambda x: x.get("total_pnl", 0), reverse=True)[0] if users else None,
        "worst_performer": sorted(users, key=lambda x: x.get("total_pnl", 0))[0] if users else None,
        "by_status": {s: len([t for t in trades if t.get("status") == s]) for s in ["CANDIDATE", "SIGNAL", "ORDER", "EXECUTED", "CLOSED", "SETTLED", "CANCELLED", "REJECTED"]},
        "scalability_test": {
            "supported": scalability_levels,
            "current": len(users),
            "architecture": "Shared market data + hash-chained ledger, no per-user duplication; market data loaded once, ledger tail cached, O(1) appends",
            "tested_levels": scalability_levels,
            "design_notes": "Adding users does not multiply trade storage; one shared trades/index.json filtered by user_id; strategy explanation served once from strategies.json; verification flags aggregated by type",
        },
        "trade_lifecycle": {
            "stages": ["CANDIDATE", "SIGNAL", "ORDER", "EXECUTED", "CLOSED", "SETTLED", "CANCELLED", "REJECTED"],
            "description": "CANDIDATE = strategy wants to trade, not yet signaled. SIGNAL = deterministic signal generated. ORDER = simulated order placed. EXECUTED = fill simulated with spread, liquidity, fees. CLOSED = sold before settlement. SETTLED = market settled, PnL finalized. CANCELLED/REJECTED = not executable.",
            "distinction": "A SIGNAL is NOT an executed trade. Signals and orders carry no position size; verifier raises CALCULATION_ERROR if one does.",
        },
        "paper_trading_realism": {
            "bid_ask_spread": "Buying YES pays YES ask; buying NO pays 1 - yes_bid. Spread crossing already in price, not double-charged as slippage.",
            "orderbook_depth": "With verified order-book snapshot, order walks real levels; slippage_vs_best measured, not assumed. Without snapshot, fill at top of book flagged ORDERBOOK_MISSING.",
            "liquidity": "Orders >50% of traded liquidity rejected as unexecutable; >10% flagged. Partial fills honored, not assumed full.",
            "fees": "Official Kalshi fee schedule: round_up(M x 0.07 x C x P x (1-P)) charged at execution, no settlement fee. Synthetic N-leg parlay pays N fees.",
            "market_status": "Only active/open markets executable; others flagged IMPOSSIBLE_EXECUTION",
        },
        "known_limitations": {
            "data": "data/raw empty in offline checkout, so synthetic fixtures flagged UNVERIFIED_DATA. Real collection via GitHub Actions where API reachable. Trade tape no history older than few hours, so candles are historical source. Native KXNFLCOMBO rare, so parlays priced as synthetic portfolios flagged SYNTHETIC_PARLAY with correlation warning.",
            "model": "Strategies requiring weekday/primetime, division, rookie QB, DVOA/Elo ratings, per-player usage cannot test hypothesis without that input — documented per strategy. Model prob in several strategies derived from market price itself, circular — documented.",
            "process": "One collection cycle captures moment, not continuous tape. Competition history preserved in ledger, but no season completed yet.",
        }
    }
    with open(os.path.join(SITE_DATA, "competition.json"), "w", encoding="utf-8") as f:
        json.dump(overview, f)

def build_docs_site():
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
    <nav class="main-nav">
      <div class="nav-group">
        <span class="nav-group-label">Competition</span>
        <a href="#" data-section="overview" class="nav-link active">Overview</a>
        <a href="#" data-section="leaderboard" class="nav-link">Leaderboard</a>
        <a href="#" data-section="upcoming" class="nav-link">Upcoming Trades</a>
        <a href="#" data-section="candidates" class="nav-link">Candidate Signals</a>
        <a href="#" data-section="recent" class="nav-link">Recent Trades</a>
        <a href="#" data-section="markets" class="nav-link">Markets</a>
      </div>
      <div class="nav-group">
        <span class="nav-group-label">Strategies</span>
        <a href="#" data-section="strategies" class="nav-link">Strategy Library</a>
        <a href="#" data-section="strategy_perf" class="nav-link">Performance</a>
        <a href="#" data-section="strategy_research" class="nav-link">Research</a>
      </div>
      <div class="nav-group">
        <span class="nav-group-label">Users</span>
        <a href="#" data-section="users" class="nav-link">User Profiles</a>
        <a href="#" data-section="trade_history" class="nav-link">Trade History</a>
      </div>
      <div class="nav-group">
        <span class="nav-group-label">Verification</span>
        <a href="#" data-section="verification" class="nav-link">Trade Verification</a>
        <a href="#" data-section="data_sources" class="nav-link">Data Sources</a>
        <a href="#" data-section="flags" class="nav-link">Flags</a>
      </div>
      <div class="nav-group">
        <span class="nav-group-label">History</span>
        <a href="#" data-section="history" class="nav-link">History & Scalability</a>
      </div>
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
      <select id="filterCategory">
        <option value="">All Categories</option>
        <option value="MARKET_BASED">Market Based</option>
        <option value="GAME_BASED">Game Based</option>
        <option value="SITUATIONAL">Situational</option>
        <option value="STATISTICAL">Statistical</option>
        <option value="CORRELATION">Correlation</option>
        <option value="PROP_BASED">Prop Based</option>
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
    <p class="subtitle">Lifecycle: Candidate → Signal → Order → Executed → Closed → Settled. Signals are NOT executed trades.</p>
    <div id="upcoming-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="candidates" class="page">
    <h2>Candidate Trade Signals</h2>
    <p class="subtitle">What every strategy currently wants to trade BEFORE simulated execution. Distinguishes: Candidate → Signal → Order → Executed → Closed → Settled</p>
    <div id="candidates-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="recent" class="page">
    <h2>Recent Trades</h2>
    <div id="recent-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="markets" class="page">
    <h2>Markets</h2>
    <p class="subtitle">Real verified Kalshi NFL markets. Prices from official Trade API v2. Each trade records market ticker, event ticker, contract, side, price, timestamps, liquidity, bid/ask, spread, fees, PnL, ROI, result, official source, verification info.</p>
    <div id="markets-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="strategies" class="page">
    <h2>Strategy Library</h2>
    <div id="strategies-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="strategy_perf" class="page">
    <h2>Strategy Performance</h2>
    <p class="subtitle">Comparison across strategy categories and individual programs</p>
    <div id="strategy-perf-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="strategy_research" class="page">
    <h2>Strategy Research</h2>
    <p class="subtitle">Research sources for strategy discovery (not price sources). Actual pricing from verified Kalshi data.</p>
    <div id="strategy-research-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="users" class="page">
    <h2>User Profiles</h2>
    <p class="subtitle">Click a username on leaderboard to view full profile: overview, performance (equity curve, PnL over time, ROI over time, win/loss distribution, trade frequency, drawdown, open exposure), trade history with verification links.</p>
    <div id="user-profile" class="profile-container"></div>
  </section>

  <section id="trade_history" class="page">
    <h2>Trade History & Ledger</h2>
    <p class="subtitle">Immutable-style ledger: every trade ever placed, upcoming, cancelled, rejected, closed, settled, with sources and calculations.</p>
    <div id="trade-history-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="verification" class="page">
    <h2>Trade Verification</h2>
    <p class="subtitle">Every trade: Leaderboard → User → Trade → Official Source. Manual verification path preserved.</p>
    <div id="verification-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="data_sources" class="page">
    <h2>Data Sources & Provenance</h2>
    <p class="subtitle">Real verified market data vs simulated trades — clearly distinguished</p>
    <div id="data-sources-content"><div class="loading">Loading...</div></div>
  </section>

  <section id="flags" class="page">
    <h2>Data Integrity / Flags</h2>
    <p class="subtitle">Missing data, unverified data, suspicious prices, liquidity problems, impossible executions, API errors, settlement inconsistencies — flagged, never hidden</p>
    <div id="flags-content"><div class="loading">Loading...</div></div>
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
     Simulated trades clearly labeled. <a href="#" data-section="verification" class="nav-link">Verification</a> |
     <a href="https://buffedlizard55-lab.github.io/MasterSite/">MasterSite</a> |
     Supports 5→1000+ users without redesign</p>
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
.main-nav { display: flex; flex-wrap: wrap; gap: 1rem; }
.nav-group { display: flex; flex-wrap: wrap; gap: 0.25rem; align-items: center; }
.nav-group-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-right: 0.25rem; font-weight: 700; }
nav a { color: #93c5fd; font-size: 0.78rem; padding: 0.3rem 0.6rem; border-radius: 4px; transition: background 0.2s; }
nav a:hover, nav a.active { background: rgba(255,255,255,0.15); text-decoration: none; color: white; }

main { max-width: 1400px; margin: 0 auto; padding: 1rem; }
.page { display: none; }
.page.active { display: block; }
section { background: var(--surface); border-radius: var(--radius); padding: 1.25rem; margin-bottom: 1rem; box-shadow: var(--shadow); }
h2 { font-size: 1.15rem; border-bottom: 2px solid var(--border); padding-bottom: 0.5rem; margin-bottom: 1rem; }
.subtitle { color: var(--text2); font-size: 0.85rem; margin-bottom: 1rem; }

.controls { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
.controls input, .controls select { padding: 0.5rem 0.75rem; border: 1px solid var(--border); border-radius: 4px; font-size: 0.85rem; background: white; }
.controls input { flex: 1; min-width: 200px; }

table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
th { background: #f8fafc; padding: 0.6rem 0.5rem; text-align: left; font-weight: 600; border-bottom: 2px solid var(--border); white-space: nowrap; }
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
.prov-official { background: var(--green-bg); color: var(--green); }
.prov-simulated { background: var(--yellow-bg); color: #a16207; }
.prov-unknown { background: #f3f4f6; color: var(--gray); }

tr.clickable { cursor: pointer; }
tr.detail-row { display: none; }
tr.detail-row.open { display: table-row; }
tr.detail-row > td { background: #f8fafc; padding: 1rem; }
.detail h4 { font-size: 0.85rem; margin: 0.75rem 0 0.4rem; color: #334155; border-bottom: 1px solid var(--border); padding-bottom: 0.2rem; }
.kv { display: flex; gap: 0.75rem; font-size: 0.78rem; padding: 0.15rem 0; }
.kv > span:first-child { min-width: 170px; color: var(--text2); }
.kv > span:last-child { word-break: break-word; }
.leg { border: 1px solid var(--border); border-radius: 6px; padding: 0.5rem; margin-bottom: 0.5rem; background: white; }
.mini-flag { font-size: 0.75rem; padding: 0.3rem 0.5rem; border-radius: 4px; margin-bottom: 0.25rem; }
.reconcile { margin-top: 0.75rem; font-size: 0.78rem; background: #f1f5f9; padding: 0.5rem; border-radius: 6px; }
.reconcile .ok { color: var(--green); margin-left: 0.5rem; font-weight: 600; }
.reconcile .bad { color: var(--red); margin-left: 0.5rem; font-weight: 600; }
.spark { width: 100%; height: 60px; display: block; background: #f8fafc; border-radius: 6px; margin-bottom: 0.5rem; }
details > summary { cursor: pointer; font-size: 0.82rem; color: var(--primary-light); }

.positive { color: var(--green); font-weight: 600; }
.negative { color: var(--red); font-weight: 600; }

.pagination { display: flex; gap: 0.25rem; margin-top: 1rem; flex-wrap: wrap; }
.pagination button { padding: 0.4rem 0.75rem; border: 1px solid var(--border); background: white; border-radius: 4px; cursor: pointer; font-size: 0.8rem; transition: all 0.15s; }
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
.profile-container .equity { font-family: monospace; font-size: 0.85rem; padding: 0.5rem; background: #f8fafc; border-radius: 4px; margin: 0.5rem 0; max-height: 200px; overflow-y: auto; }

footer { background: #0f172a; color: #94a3b8; padding: 1.5rem; text-align: center; font-size: 0.8rem; }
footer a { color: #93c5fd; }
footer .small { font-size: 0.7rem; margin-top: 0.5rem; opacity: 0.7; }

@media (max-width: 768px) {
  header h1 { font-size: 1rem; }
  nav a { font-size: 0.7rem; padding: 0.2rem 0.4rem; }
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  table { font-size: 0.75rem; }
  td, th { padding: 0.35rem; }
  .main-nav { gap: 0.5rem; }
}
"""

def _build_js() -> str:
    return r"""
// NFL Parlay Competition - Client-side app with grouped nav and full lifecycle
async function fetchJSON(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) return null;
    return await res.json();
  } catch(e) { return null; }
}
function fmt$(n) { if (n == null) return '-'; const v = Number(n); return (v >= 0 ? '+' : '') + '$' + v.toFixed(2); }
function fmtPct(n) { if (n == null) return '-'; const v = Number(n); return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
function fmtDate(s) { if (!s) return '-'; try { return new Date(s).toLocaleString(); } catch(e) { return s; } }
function fmtShort(s) { if (!s) return '-'; try { return new Date(s).toLocaleDateString(); } catch(e) { return s; } }
function cls$(n) { return n >= 0 ? 'positive' : 'negative'; }
function badge(status) { const s = (status || '').toLowerCase(); return `<span class="badge badge-${s}">${status}</span>`; }
function provBadge(t) {
  const src = t.settlement_result_source; if (!src) return '';
  const map = {
    OFFICIAL: ['prov-official', 'OFFICIAL RESULT', 'Read from settled Kalshi market result'],
    SIMULATED: ['prov-simulated', 'SIMULATED SETTLEMENT', 'No official Kalshi result stored: drawn from market-implied prob. Not verified.'],
    PARTIAL: ['prov-simulated', 'PARTLY SIMULATED', 'Some legs official, others simulated'],
    UNKNOWN: ['prov-unknown', 'PROVENANCE UNKNOWN', 'Not recorded'],
  };
  const [cls, label, title] = map[src] || map.UNKNOWN;
  return ` <span class="badge ${cls}" title="${title}">${label}</span>`;
}
function provCell(t) {
  const src = t.settlement_result_source; if (!src) return '<span style="color:#94a3b8">-</span>';
  if (src === 'OFFICIAL') return '<span style="color:#16a34a">official</span>';
  if (src === 'UNKNOWN') return '<span style="color:#64748b">unknown</span>';
  return '<span style="color:#ca8a04">simulated</span>';
}
function tradeDetail(t) {
  const legs = (t.legs || []).map((l, i) => `
    <div class="leg">
      <div><strong>Leg ${i+1}</strong> — <code>${l.market_ticker || l.t || ''}</code></div>
      <div class="kv"><span>Event</span><span><code>${l.event_ticker || l.e || ''}</code></span></div>
      <div class="kv"><span>Series</span><span><code>${l.series_ticker || l.s || ''}</code></span></div>
      <div class="kv"><span>Contract</span><span><code>${l.contract || l.market_ticker || l.t || ''}</code></span></div>
      <div class="kv"><span>Side</span><span>${l.side || ''}</span></div>
      <div class="kv"><span>Entry price</span><span>${l.entry_price ?? l.px ?? '-'}</span></div>
      <div class="kv"><span>Exec price</span><span>${l.exec_price ?? l.exec ?? '-'}</span></div>
      <div class="kv"><span>Proposed / Current</span><span>${l.proposed_entry_price ?? '-'} / ${l.current_verified_price ?? '-'}</span></div>
      <div class="kv"><span>Quantity</span><span>${l.quantity ?? l.qty ?? '-'}${l.quantity_requested != null && l.quantity_requested !== l.quantity ? ' (requested ' + l.quantity_requested + ')' : ''}</span></div>
      <div class="kv"><span>Position size</span><span>${l.position_size ?? '-'}</span></div>
      <div class="kv"><span>Bid / Ask</span><span>${l.bid_at_entry ?? l.bid ?? '-'} / ${l.ask_at_entry ?? l.ask ?? '-'}</span></div>
      <div class="kv"><span>Spread</span><span>${l.spread ?? l.spr ?? '-'}</span></div>
      <div class="kv"><span>Implied prob</span><span>${l.implied_prob ?? l.ip ?? '-'}</span></div>
      <div class="kv"><span>Liquidity</span><span>${l.liquidity_at_entry ?? l.liq ?? l.liquidity ?? '-'}</span></div>
      <div class="kv"><span>Expiration</span><span>${l.expiration_date ?? l.exp ?? '-'}</span></div>
      <div class="kv"><span>Snapshot file</span><span><code>${l.source_file || l.src || ''}</code></span></div>
      <div class="kv"><span>SHA-256</span><span><code>${l.source_sha256 || l.sha || ''}</code></span></div>
      <div class="kv"><span>Entry timestamp</span><span>${l.entry_timestamp || l.ts || ''}</span></div>
      <div class="kv"><span>Official source</span><span><a href="${l.source_url || l.u || '#'}" target="_blank">${l.source_url || l.u || ''}</a></span></div>
      <div class="kv"><span>Verification</span><span><a href="${l.verification_url || l.v || '#'}" target="_blank">${l.verification_url || l.v || ''}</a></span></div>
    </div>`).join('');
  const flags = (t.flags || []).map(f => `<div class="mini-flag flag-${f.severity||'low'}"><strong>${f.flag_type}</strong> [${f.severity}] ${f.message}</div>`).join('') || '<div style="color:#16a34a">No flags</div>';
  const sources = (t.official_sources || []).map(s => `<div><a href="${s}" target="_blank">${s}</a></div>`).join('') || '<div>-</div>';
  return `
    <div class="detail">
      <h4>Trade record — ${t.trade_id || ''}</h4>
      <div class="kv"><span>Status</span><span>${t.status || ''} (Candidate → Signal → Order → Executed → Closed → Settled)</span></div>
      <div class="kv"><span>Result</span><span>${t.result || ''}</span></div>
      <div class="kv"><span>Settlement source</span><span>${t.settlement_result_source || 'not recorded'}</span></div>
      ${t.settlement_note ? `<div class="kv"><span>Note</span><span>${t.settlement_note}</span></div>` : ''}
      <div class="kv"><span>Market type</span><span>${t.market_type || ''}</span></div>
      <div class="kv"><span>Is native combo</span><span>${t.is_native_kalshi_combo ? 'YES native KXNFLCOMBO' : 'NO synthetic parlay'}</span></div>
      <div class="kv"><span>Created</span><span>${fmtDate(t.created_at)}</span></div>
      <div class="kv"><span>Updated</span><span>${fmtDate(t.updated_at)}</span></div>
      <div class="kv"><span>Why entered</span><span>${t.why_entered || t.conditions_required || ''}</span></div>
      <div class="kv"><span>Expected value</span><span>${t.expected_value ?? '-'}</span></div>
      <div class="kv"><span>Proposed entry</span><span>${t.proposed_entry_price ?? '-'}</span></div>
      <div class="kv"><span>Current verified price</span><span>${t.current_verified_price ?? '-'}</span></div>
      <div class="kv"><span>Position size / $</span><span>${t.position_size ?? '-'} / $${(t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Required liquidity</span><span>${t.required_liquidity ?? '-'}</span></div>
      <div class="kv"><span>Executable?</span><span>${t.is_executable != null ? (t.is_executable ? 'YES' : 'NO') : '-'}</span></div>
      <div class="kv"><span>Invalidation</span><span>${t.invalidation_conditions || ''}</span></div>
      <div class="kv"><span>Cost</span><span>$${(t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Fees</span><span>$${(t.fees ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Total debit</span><span>$${(t.total_debit_dollars ?? t.position_size_dollars ?? 0).toFixed(2)}</span></div>
      <div class="kv"><span>Payout</span><span>${t.payout_dollars != null ? '$' + Number(t.payout_dollars).toFixed(2) : '-'}</span></div>
      <div class="kv"><span>PnL</span><span class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</span></div>
      <div class="kv"><span>ROI</span><span class="${cls$(t.roi_percent)}">${t.roi_percent != null ? fmtPct(t.roi_percent) : '-'}</span></div>
      <div class="kv"><span>Fee model</span><span><code>${t.fee_model || 'not recorded'}</code></span></div>
      <h4>Legs (${(t.legs||[]).length}) — each records market ticker, event ticker, contract, side, entry price, exit price, timestamps, expiration, quantity, position size, implied prob, liquidity, bid/ask, spread, slippage, fees, PnL, ROI, result, official source, verification</h4>${legs}
      <h4>Official sources (verify here)</h4>${sources}
      <h4>Flags (${(t.flags||[]).length})</h4>${flags}
    </div>`;
}
function reconcile(t) {
  if (t.pnl_dollars == null || t.position_size_dollars == null) return '';
  const payout = t.payout_dollars != null ? t.payout_dollars : (t.position_size_dollars + (t.fees||0) + t.pnl_dollars);
  const check = payout - t.position_size_dollars - (t.fees || 0);
  const ok = Math.abs(check - t.pnl_dollars) < 0.02;
  return `<div class="reconcile"><code>payout ${fmtMoneyPlain(payout)} - cost ${fmtMoneyPlain(t.position_size_dollars)} - fees ${fmtMoneyPlain(t.fees||0)} = ${fmtMoneyPlain(check)}</code>${ok ? '<span class="ok">checkable: matches recorded PnL</span>' : '<span class="bad">MISMATCH vs recorded PnL ' + fmtMoneyPlain(t.pnl_dollars) + '</span>'}</div>`;
}
function fmtMoneyPlain(n) { return '$' + Number(n || 0).toFixed(2); }
function toggleDetail(tradeId) { const el = document.getElementById('detail-' + tradeId); if (el) el.classList.toggle('open'); }

let currentPage = 1; let currentSearch = ''; let currentSort = 'rank'; let currentPageSize = 25; let currentCategory = '';

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const section = link.dataset.section; if (!section) return;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const el = document.getElementById(section); if (el) el.classList.add('active');
    link.classList.add('active');
    if (section === 'leaderboard') loadLeaderboard();
    if (section === 'upcoming') loadTrades('upcoming-content', 'upcoming.json');
    if (section === 'candidates') loadTrades('candidates-content', 'candidates.json');
    if (section === 'recent') loadTrades('recent-content', 'recent.json');
    if (section === 'markets') loadMarkets();
    if (section === 'strategies') loadStrategies();
    if (section === 'strategy_perf') loadStrategyPerf();
    if (section === 'strategy_research') loadStrategyResearch();
    if (section === 'trade_history') loadTradeHistory();
    if (section === 'verification') loadVerification();
    if (section === 'data_sources') loadDataSources();
    if (section === 'flags') loadFlags();
    if (section === 'history') loadHistory();
  });
});

async function loadOverview() {
  const data = await fetchJSON('site_data/competition.json'); if (!data) { document.getElementById('overview-content').innerHTML = '<p>No competition data yet. Run simulate.py first.</p>'; return; }
  const top = data.top_performer; const worst = data.worst_performer; const statusCounts = data.by_status || {}; const exec = (statusCounts.EXECUTED||0) + (statusCounts.SETTLED||0) + (statusCounts.CLOSED||0);
  const prov = data.data_provenance || {};
  document.getElementById('overview-content').innerHTML = `
    <div class="card" style="border-left:4px solid ${prov.real_kalshi_data_present ? '#16a34a' : '#ca8a04'}">
      <h3>Data Provenance</h3>
      <p><strong>Real Kalshi data present:</strong> ${prov.real_kalshi_data_present ? 'YES' : 'NO (synthetic fixtures)'}</p>
      <p style="font-size:0.8rem;color:#475569">${prov.note || ''}</p>
      <p style="font-size:0.75rem;color:#64748b">Real verified data vs simulated trades clearly distinguished. Every price traceable to fetch manifest SHA-256.</p>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Season</div><div class="value">${data.season}</div></div>
      <div class="stat-card"><div class="label">Period</div><div class="value" style="font-size:0.9rem">${data.competition_period || ''}</div></div>
      <div class="stat-card"><div class="label">Status</div><div class="value">${data.status}</div></div>
      <div class="stat-card"><div class="label">Users</div><div class="value">${data.total_users}</div></div>
      <div class="stat-card"><div class="label">Total Trades</div><div class="value">${data.total_trades}</div></div>
      <div class="stat-card"><div class="label">Ledger Entries</div><div class="value">${data.ledger_entries}</div></div>
      <div class="stat-card"><div class="label">Total PnL</div><div class="value ${cls$(data.total_pnl)}">${fmt$(data.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">Avg ROI</div><div class="value ${cls$(data.avg_roi)}">${fmtPct(data.avg_roi)}</div></div>
    </div>
    <div class="card"><h3>Top Performer</h3><p>${top ? `<strong>${top.username}</strong> — ${top.strategy_name}<br>PnL ${fmt$(top.total_pnl)} | ROI ${fmtPct(top.roi_percent)} | ${top.wins}W-${top.losses}L` : 'None'}</p></div>
    <div class="card"><h3>Worst Performer</h3><p>${worst ? `<strong>${worst.username}</strong> — ${worst.strategy_name}<br>PnL ${fmt$(worst.total_pnl)} | ROI ${fmtPct(worst.roi_percent)} | ${worst.wins}W-${worst.losses}L` : 'None'}</p></div>
    <div class="card"><h3>Trade Activity</h3><p>Executed: ${exec} | Candidate: ${statusCounts.CANDIDATE||0} | Signal: ${statusCounts.SIGNAL||0} | Order: ${statusCounts.ORDER||0} | Rejected: ${statusCounts.REJECTED||0} | Settled: ${statusCounts.SETTLED||0} | Closed: ${statusCounts.CLOSED||0}</p><p class="subtitle">Lifecycle: Candidate → Signal → Order → Executed → Closed → Settled. Candidate and Signal are NOT executed trades.</p></div>
    <div class="card"><h3>Trade Lifecycle</h3><p>${(data.trade_lifecycle?.stages||[]).join(' → ')}</p><p style="font-size:0.8rem">${data.trade_lifecycle?.description||''}</p><p style="font-size:0.75rem;color:#ca8a04">${data.trade_lifecycle?.distinction||''}</p></div>
    <div class="card"><h3>Paper Trading Realism</h3><pre style="white-space:pre-wrap">${JSON.stringify(data.paper_trading_realism||{}, null, 2)}</pre></div>
    <div class="card"><h3>Scalability</h3><p>Supports ${(data.scalability_test?.supported||[]).join(' → ')} users. Current: <strong>${data.scalability_test?.current}</strong>.</p><p>${data.scalability_test?.architecture}</p><p style="font-size:0.75rem">${data.scalability_test?.design_notes||''}</p></div>
    <div class="card"><h3>Known Limitations</h3><pre style="white-space:pre-wrap">${JSON.stringify(data.known_limitations||{}, null, 2)}</pre></div>
  `;
}

async function loadLeaderboard() {
  const data = await fetchJSON(`site_data/leaderboard_page_${currentPage}.json`);
  if (!data) {
    const all = await fetchJSON('site_data/leaderboard.json');
    if (!all) { document.getElementById('leaderboard-content').innerHTML = '<p>No users yet.</p>'; return; }
    renderLeaderboard(all.users, all.count, 1, 1); return;
  }
  renderLeaderboard(data.users, data.total, data.page, data.total_pages);
}
function renderLeaderboard(users, total, page, totalPages) {
  let filtered = users || [];
  if (currentSearch) {
    const s = currentSearch.toLowerCase();
    filtered = filtered.filter(u => (u.username||'').toLowerCase().includes(s) || (u.strategy_name||'').toLowerCase().includes(s));
  }
  if (currentCategory) {
    filtered = filtered.filter(u => {
      const strat = strategyCache ? strategyCache[u.strategy_id] : null;
      return strat ? strat.category === currentCategory : true;
    });
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
  let html = `<div class="table-container"><table><thead><tr><th>#</th><th>Username</th><th>Strategy</th><th>Bankroll</th><th>PnL</th><th>ROI</th><th>W-L</th><th>Win%</th><th>Trades</th><th>Open</th><th>Last Trade</th></tr></thead><tbody>`;
  for (const u of slice) {
    html += `<tr><td>${u.rank || '-'}</td><td><a href="#" onclick="loadProfile('${u.user_id}');return false;" title="${u.strategy_description||''}">${u.username}</a></td><td title="${u.strategy_description||''}">${(u.strategy_name||'').slice(0,30)}</td><td>$${Number(u.current_bankroll||0).toFixed(0)}</td><td class="${cls$(u.total_pnl)}">${fmt$(u.total_pnl)}</td><td class="${cls$(u.roi_percent)}">${fmtPct(u.roi_percent)}</td><td>${u.wins||0}-${u.losses||0}</td><td>${u.win_rate||0}%</td><td>${u.total_trades||0}</td><td>${(u.open_trades||[]).length}</td><td>${fmtShort(u.last_trade_at)}</td></tr>`;
  }
  html += '</tbody></table></div>';
  document.getElementById('leaderboard-content').innerHTML = html;
  const tp = Math.ceil(total / currentPageSize) || 1;
  let pag = `<span style="margin-right:0.5rem;font-size:0.8rem;color:#64748b">${filtered.length} filtered / ${total} total users</span>`;
  for (let i = 1; i <= Math.min(tp, 15); i++) pag += `<button class="${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
  if (tp > 15) pag += `<span>...</span><button onclick="goPage(${tp})\">${tp}</button>`;
  document.getElementById('pagination').innerHTML = pag;
}
function goPage(p) { currentPage = p; loadLeaderboard(); }

let tradeIndexCache = null;
async function getTradeIndex() {
  if (tradeIndexCache) return tradeIndexCache;
  const data = await fetchJSON('site_data/trades/index.json');
  tradeIndexCache = data ? (data.trades || []) : []; return tradeIndexCache;
}
function expandLeg(l) {
  if (l.market_ticker) return l;
  return {
    market_ticker: l.t, event_ticker: l.e, series_ticker: l.s, contract: l.contract || l.t,
    side: l.side, entry_price: l.px, exec_price: l.exec, quantity: l.qty, quantity_requested: l.qty_req,
    bid_at_entry: l.bid, ask_at_entry: l.ask, spread: l.spr, implied_prob: l.ip, liquidity_at_entry: l.liq, liquidity: l.liq,
    reason: l.req, model_prob: l.mp, source_file: l.src, source_sha256: l.sha, entry_timestamp: l.ts, source_url: l.u, verification_url: l.v,
    expiration_date: l.exp, position_size: l.pos_size, proposed_entry_price: l.px, current_verified_price: l.px,
  };
}
function expandTrade(t) { if (!t || !t.legs) return t; return { ...t, legs: t.legs.map(expandLeg) }; }

let strategyCache = null;
async function getStrategies() {
  if (strategyCache) return strategyCache;
  const data = await fetchJSON('site_data/strategies.json');
  strategyCache = {}; for (const s of ((data && data.strategies) || [])) strategyCache[s.strategy_id] = s; return strategyCache;
}

async function loadProfile(userId) {
  const data = await fetchJSON(`site_data/users/${userId}.json`);
  if (!data) { document.getElementById('user-profile').innerHTML = '<p>User not found.</p>'; return; }
  const index = await getTradeIndex(); const mine = index.filter(t => t.user_id === userId).map(expandTrade); data.trades = mine;
  const strategy = (await getStrategies())[data.strategy_ref] || {}; const u = data.user; const s = data.stats;
  let html = `
    <div class="card"><h3>${u.username} — ${u.strategy_name}</h3><p class="subtitle">${u.strategy_description || ''}</p>
      <div class="kv"><div>Category</div><div>${strategy.category || '-'}</div></div>
      <details><summary>Full Strategy Explanation (what info uses, entry, avoid, sizing, EV, why work/fail, evidence)</summary><pre style="white-space:pre-wrap;margin-top:0.5rem">${strategy.long_explanation || 'not available'}</pre></details>
      <details><summary>Strategy sources (${(strategy.sources||[]).length})</summary>${(strategy.sources||[]).map(src => `<div><a href="${src}" target="_blank">${src}</a></div>`).join('')}</details>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Starting Bankroll</div><div class="value">$${Number(u.starting_bankroll).toFixed(0)}</div></div>
      <div class="stat-card"><div class="label">Current Bankroll</div><div class="value ${cls$(u.current_bankroll - u.starting_bankroll)}\">$${Number(u.current_bankroll).toFixed(0)}</div></div>
      <div class="stat-card"><div class="label">Total PnL</div><div class="value ${cls$(u.total_pnl)}\">${fmt$(u.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">ROI</div><div class="value ${cls$(u.roi_percent)}\">${fmtPct(u.roi_percent)}</div></div>
      <div class="stat-card"><div class="label">Rank</div><div class="value">#${u.rank || '-'}</div></div>
      <div class="stat-card"><div class="label">Win Rate</div><div class="value">${u.win_rate || 0}%</div></div>
      <div class="stat-card"><div class="label">Trades</div><div class="value">${u.total_trades || 0}</div></div>
      <div class="stat-card"><div class="label">Open Exposure</div><div class="value">$${(s.open_exposure||0).toFixed(2)}</div></div>
      <div class="stat-card"><div class="label">Trade Freq / Day</div><div class="value">${s.trade_frequency_per_day ?? 0}</div></div>
    </div>
    <div class="card"><h3>Performance</h3>
      <div class="stat-grid">
        <div class="stat-card"><div class="label">Wins / Losses</div><div class="value">${s.wins} / ${s.losses}</div></div>
        <div class="stat-card"><div class="label">Max Drawdown</div><div class="value">${s.max_drawdown_pct ?? 0}%</div></div>
        <div class="stat-card"><div class="label">Gross Profit</div><div class="value positive">${fmt$(s.gross_profit)}</div></div>
        <div class="stat-card"><div class="label">Gross Loss</div><div class="value negative">${fmt$(s.gross_loss)}</div></div>
        <div class="stat-card"><div class="label">Total Fees Paid</div><div class="value">$${(s.total_fees||0).toFixed(2)}</div></div>
        <div class="stat-card"><div class="label">Total Volume</div><div class="value">$${(s.total_volume||0).toFixed(2)}</div></div>
        <div class="stat-card"><div class="label">Avg PnL / Trade</div><div class="value ${cls$(s.avg_trade_pnl)}\">${fmt$(s.avg_trade_pnl)}</div></div>
        <div class="stat-card"><div class="label">Avg ROI / Trade</div><div class="value ${cls$(s.avg_roi_per_trade)}\">${fmtPct(s.avg_roi_per_trade)}</div></div>
        <div class="stat-card"><div class="label">Open / Closed</div><div class="value">${s.open_positions} / ${s.closed_positions}</div></div>
      </div>
      <p class="subtitle">Settlement provenance: ${Object.entries(s.settlement_sources || {}).filter(([,v]) => v).map(([k,v]) => `${k} ${v}`).join(' · ') || 'no settled trades yet'} — SIMULATED outcome is draw from market-implied probability, not verified result.</p>
    </div>`;

  const eq = data.equity_curve || [];
  if (eq.length > 0) {
    const values = eq.map(p => Number(p.bankroll)); const lo = Math.min(...values), hi = Math.max(...values); const span = (hi - lo) || 1;
    const pts = values.map((v, i) => { const x = values.length === 1 ? 100 : (i / (values.length - 1)) * 100; const y = 30 - ((v - lo) / span) * 28; return `${x.toFixed(2)},${y.toFixed(2)}`; }).join(' ');
    html += `<div class="card"><h3>Equity Curve — PnL over time (${eq.length} points)</h3><svg viewBox="0 0 100 30" preserveAspectRatio="none" class="spark"><polyline points="${pts}" fill="none" stroke="#1e40af" stroke-width="0.6"/></svg><div class="kv"><span>High</span><span>$${hi.toFixed(2)}</span></div><div class="kv"><span>Low</span><span>$${lo.toFixed(2)}</span></div><div class="kv"><span>Latest</span><span>$${values[values.length-1].toFixed(2)}</span></div><details><summary>Full history</summary><div class="equity">`;
    for (const pt of eq.slice(-50)) html += `${fmtDate(pt.t)}: $${Number(pt.bankroll).toFixed(2)} (PnL: ${fmt$(pt.pnl)})<br>`;
    html += '</div></details></div>';
  }
  const roiHist = data.roi_history || [];
  if (roiHist.length > 0) {
    const vals = roiHist.map(p => Number(p.roi)); const lo = Math.min(...vals), hi = Math.max(...vals); const span = (hi - lo) || 1;
    const pts = vals.map((v, i) => { const x = vals.length === 1 ? 100 : (i / (vals.length - 1)) * 100; const y = 30 - ((v - lo) / span) * 28; return `${x.toFixed(2)},${y.toFixed(2)}`; }).join(' ');
    html += `<div class="card"><h3>ROI over Time</h3><svg viewBox="0 0 100 30" preserveAspectRatio="none" class="spark"><polyline points="${pts}" fill="none" stroke="#16a34a" stroke-width="0.6"/></svg><div class="kv"><span>High ROI</span><span>${fmtPct(hi)}</span></div><div class="kv"><span>Low ROI</span><span>${fmtPct(lo)}</span></div><div class="kv"><span>Latest ROI</span><span>${fmtPct(vals[vals.length-1])}</span></div></div>`;
  }
  const dist = data.pnl_distribution || {};
  if ((dist.wins && dist.wins.length) || (dist.losses && dist.losses.length)) {
    html += `<div class="card"><h3>Win/Loss Distribution</h3><p>Wins: ${(dist.wins||[]).length} — avg ${dist.wins.length ? '$' + (dist.wins.reduce((a,b)=>a+b,0)/dist.wins.length).toFixed(2) : '-'}</p><p>Losses: ${(dist.losses||[]).length} — avg ${dist.losses.length ? '$' + (dist.losses.reduce((a,b)=>a+b,0)/dist.losses.length).toFixed(2) : '-'}</p></div>`;
  }

  const trades = data.trades || [];
  html += `<div class="card"><h3>Trade History (${trades.length}) — searchable, paginated, verifiable</h3><p class="subtitle">Click any row to inspect full record: every leg, every price, snapshot file, fee model, official source link. Leaderboard → User → Trade → Official Source</p>`;
  if (trades.length === 0) html += '<p>No trades yet.</p>';
  else {
    html += `<div class="table-container"><table><thead><tr><th>ID</th><th>Legs</th><th>Entry</th><th>Exit</th><th>Cost</th><th>Fees</th><th>PnL</th><th>ROI</th><th>Status</th><th>Settlement</th></tr></thead><tbody>`;
    for (const t of trades.slice(0, 50)) {
      const legs = (t.legs || []).map(l => `${(l.market_ticker||'').slice(0,30)} ${l.side}@${l.entry_price || l.px}`).join('<br>'); const tid = t.trade_id || '';
      html += `<tr class="clickable" onclick="toggleDetail('${tid}')"><td title="${tid}">${tid.slice(0, 12)} ▸</td><td style="font-size:0.75rem">${legs}</td><td>${t.entry_price_combined || '-'}</td><td>${t.exit_price_combined ?? t.settlement_price ?? '-'}</td><td>$${(t.position_size_dollars || 0).toFixed(2)}</td><td>$${(t.fees || 0).toFixed(2)}</td><td class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</td><td class="${cls$(t.roi_percent)}">${t.roi_percent != null ? fmtPct(t.roi_percent) : '-'}</td><td>${badge(t.status)}</td><td>${provCell(t)}</td></tr><tr class="detail-row" id="detail-${tid}"><td colspan="10">${tradeDetail(t)}${reconcile(t)}</td></tr>`;
    }
    html += '</tbody></table></div>';
  }
  html += '</div>';
  document.getElementById('user-profile').innerHTML = html;
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active')); document.getElementById('users').classList.add('active');
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active')); document.querySelector('[data-section="users"]').classList.add('active');
  document.getElementById('user-profile').scrollIntoView({ behavior: 'smooth' });
}

async function loadTrades(sectionId, fileName) {
  const data = await fetchJSON(`site_data/trades/${fileName}`);
  if (!data) { document.getElementById(sectionId).innerHTML = '<p>No trades.</p>'; return; }
  const trades = data.trades || data.candidates || [];
  if (trades.length === 0) { document.getElementById(sectionId).innerHTML = `<p>No ${fileName.replace('.json','')} trades yet.</p>`; return; }
  let html = `<p class="subtitle">Showing ${Math.min(trades.length, 50)} of ${data.count} trades — click a row for full verifiable record. Lifecycle: Candidate → Signal → Order → Executed → Closed → Settled</p>`;
  html += `<div class="table-container"><table><thead><tr><th>ID</th><th>User</th><th>Strategy</th><th>Legs</th><th>Proposed / Entry</th><th>Current / Cost</th><th>EV</th><th>Executable</th><th>Status</th><th>Created</th></tr></thead><tbody>`;
  for (const t of trades.slice(0, 50)) {
    const legs = (t.legs || []).map(l => `${(l.market_ticker||l.t||'').slice(0,25)} ${l.side}@${l.entry_price || l.px || l.proposed_entry_price}`).join('<br>'); const tid = t.trade_id || '';
    html += `<tr class="clickable" onclick="toggleDetail('${tid}')"><td title="${tid}">${tid.slice(0, 12)} ▸</td><td><a href="#" onclick="loadProfile('${t.user_id}');return false;">${t.username || t.user_id?.slice(0,12)}</a></td><td>${(t.strategy_id||'').replace('STRAT_','').slice(0,20)}</td><td style="font-size:0.75rem">${legs}</td><td>${t.proposed_entry_price ?? t.entry_price_combined ?? '-'}</td><td>${t.current_verified_price ?? t.position_size_dollars ?? '-'}</td><td>${t.expected_value ?? '-'}</td><td>${t.is_executable != null ? (t.is_executable ? 'YES' : 'NO') : (t.status === 'CANDIDATE' ? 'check' : '-')}</td><td>${badge(t.status)}${provBadge(t)}</td><td>${fmtShort(t.created_at)}</td></tr><tr class="detail-row" id="detail-${tid}"><td colspan="10">${tradeDetail(t)}${reconcile(t)}</td></tr>`;
  }
  html += '</tbody></table></div>'; document.getElementById(sectionId).innerHTML = html;
}

async function loadMarkets() {
  const data = await fetchJSON('site_data/markets.json');
  if (!data) { document.getElementById('markets-content').innerHTML = '<p>No market data.</p>'; return; }
  let html = `<p class="subtitle">Events: ${(data.events||[]).length} | Markets: ${(data.markets||[]).length} | ${data.note||''}</p>`;
  if ((data.markets||[]).length === 0) html += '<p>No market snapshots. Run collect.py to fetch real Kalshi data (works in GitHub Actions where API reachable). Synthetic fixtures flagged UNVERIFIED_DATA for offline testing.</p>';
  else {
    html += `<div class="table-container"><table><thead><tr><th>Ticker</th><th>Event</th><th>Series</th><th>Status</th><th>Bid/Ask</th><th>Last</th><th>Volume</th><th>Liquidity</th><th>Verify</th></tr></thead><tbody>`;
    for (const m of (data.markets||[]).slice(0, 80)) {
      html += `<tr><td title="${m.ticker}">${(m.ticker||'').slice(0,35)}</td><td>${(m.event_ticker||'').slice(0,30)}</td><td>${m.series_ticker}</td><td>${badge(m.status)}</td><td>${m.yes_bid||'-'}/${m.yes_ask||'-'}</td><td>${m.last_price||'-'}</td><td>${m.volume ? Number(m.volume).toFixed(0) : '-'}</td><td>${m.liquidity ? Number(m.liquidity).toFixed(0) : '-'}</td><td><a href="https://kalshi.com/markets/${m.ticker}" target="_blank">Kalshi</a> <a href="https://api.elections.kalshi.com/trade-api/v2/markets/${m.ticker}" target="_blank">API</a></td></tr>`;
    }
    html += '</tbody></table></div>';
  }
  document.getElementById('markets-content').innerHTML = html;
}

async function loadStrategies() {
  const data = await fetchJSON('site_data/strategies.json');
  if (!data) { document.getElementById('strategies-content').innerHTML = '<p>No strategies.</p>'; return; }
  let html = `<p class="subtitle">${data.count} distinct strategies across categories — each meaningfully different, not just username randomization. Each explains what info uses, entry, avoid, sizing, EV, why work/fail, evidence.</p>`;
  const byCategory = {}; for (const s of (data.strategies || [])) { const cat = s.category || 'Other'; if (!byCategory[cat]) byCategory[cat] = []; byCategory[cat].push(s); }
  for (const [cat, strats] of Object.entries(byCategory)) {
    html += `<h3 style="margin:1rem 0 0.5rem;font-size:0.95rem;color:#475569">${cat} (${strats.length})</h3>`;
    for (const s of strats) {
      html += `<div class="card"><strong>${s.name}</strong> <span style="color:#64748b;font-size:0.75rem">${s.strategy_id}</span><br><em style="font-size:0.85rem">${s.description}</em><details style="margin-top:0.5rem"><summary>Full explanation (info, entry, avoid, sizing, EV, work/fail, evidence)</summary><pre style="white-space:pre-wrap;font-size:0.78rem">${s.long_explanation || ''}</pre></details><div style="margin-top:0.5rem;font-size:0.8rem;color:#475569">Users: ${s.performance.users} | PnL: ${fmt$(s.performance.total_pnl)} | Avg ROI: ${fmtPct(s.performance.avg_roi)} | Trades: ${s.performance.trades} | Wins ${s.performance.wins} Losses ${s.performance.losses}</div><div style="font-size:0.75rem;color:#94a3b8">Sources: ${(s.sources||[]).join(', ')}</div></div>`;
    }
  }
  document.getElementById('strategies-content').innerHTML = html;
}
async function loadStrategyPerf() {
  const data = await fetchJSON('site_data/strategies.json');
  if (!data) { document.getElementById('strategy-perf-content').innerHTML = '<p>No data.</p>'; return; }
  const strats = data.strategies || [];
  const byCat = {};
  for (const s of strats) { const c = s.category || 'Other'; if (!byCat[c]) byCat[c] = {pnl:0, users:0, trades:0, wins:0, losses:0, count:0}; byCat[c].pnl += s.performance.total_pnl; byCat[c].users += s.performance.users; byCat[c].trades += s.performance.trades; byCat[c].wins += s.performance.wins; byCat[c].losses += s.performance.losses; byCat[c].count += 1; }
  let html = `<div class="table-container"><table><thead><tr><th>Category</th><th>Strategies</th><th>Users</th><th>Total PnL</th><th>Trades</th><th>W-L</th><th>Avg per strat</th></tr></thead><tbody>`;
  for (const [cat, v] of Object.entries(byCat)) {
    html += `<tr><td><strong>${cat}</strong></td><td>${v.count}</td><td>${v.users}</td><td class="${cls$(v.pnl)}">${fmt$(v.pnl)}</td><td>${v.trades}</td><td>${v.wins}-${v.losses}</td><td>${fmt$(v.pnl / Math.max(1,v.count))}</td></tr>`;
  }
  html += '</tbody></table></div>';
  html += `<h3 style="margin-top:1rem">Individual Strategy Performance</h3><div class="table-container"><table><thead><tr><th>Strategy</th><th>Category</th><th>Users</th><th>PnL</th><th>Avg ROI</th><th>Trades</th><th>W-L</th></tr></thead><tbody>`;
  for (const s of strats.sort((a,b)=>b.performance.total_pnl - a.performance.total_pnl)) {
    html += `<tr><td>${s.name}</td><td>${s.category}</td><td>${s.performance.users}</td><td class="${cls$(s.performance.total_pnl)}">${fmt$(s.performance.total_pnl)}</td><td class="${cls$(s.performance.avg_roi)}">${fmtPct(s.performance.avg_roi)}</td><td>${s.performance.trades}</td><td>${s.performance.wins}-${s.performance.losses}</td></tr>`;
  }
  html += '</tbody></table></div>';
  document.getElementById('strategy-perf-content').innerHTML = html;
}
async function loadStrategyResearch() {
  const data = await fetchJSON('site_data/strategy_research.json');
  if (!data) { document.getElementById('strategy-research-content').innerHTML = '<p>No research data.</p>'; return; }
  let html = `<div class="card"><h3>Discovery Sources (not price sources)</h3><p class="subtitle">Strategy discovery from public sources, but actual pricing from verified Kalshi data only. No fabricated prices.</p>`;
  for (const src of (data.discovery_sources||[])) html += `<div class="kv"><span><a href="${src.url}" target="_blank">${src.source}</a></span><span>${src.use}</span></div>`;
  html += '</div><div class="card"><h3>Categories</h3>';
  for (const [k,v] of Object.entries(data.strategy_categories||{})) html += `<div class="kv"><span><strong>${k}</strong></span><span>${v}</span></div>`;
  html += `</div><div class="card"><h3>Research Notes</h3><pre style="white-space:pre-wrap">${data.research_notes||''}</pre></div>`;
  document.getElementById('strategy-research-content').innerHTML = html;
}
async function loadTradeHistory() {
  const summary = await fetchJSON('site_data/trades/ledger_summary.json');
  const recent = await fetchJSON('site_data/trades/recent.json');
  const closed = await fetchJSON('site_data/trades/closed.json');
  const rejected = await fetchJSON('site_data/trades/rejected.json');
  let html = `<div class="stat-grid"><div class="stat-card"><div class="label">Distinct Trades</div><div class="value">${summary?.total||0}</div></div><div class="stat-card"><div class="label">Ledger Entries</div><div class="value">${summary?.ledger_entries||0}</div></div>`;
  for (const [k,v] of Object.entries(summary?.by_status||{})) html += `<div class="stat-card"><div class="label">${k}</div><div class="value">${v}</div></div>`;
  html += `<div class="card"><h3>Ledger Note</h3><p style="font-size:0.8rem">${summary?.note||''}</p><p style="font-size:0.75rem;color:#64748b">Hash-chained append-only ledger: data/competition/ledger.jsonl — SINGLE SOURCE OF TRUTH. O(1) appends, tail cached. Shared market data in data/raw/kalshi not duplicated per user.</p></div>`;
  html += `<div class="card"><h3>Recent Trades (${recent?.count||0})</h3>`; if (recent && recent.trades) { html += `<div class="table-container"><table><thead><tr><th>ID</th><th>User</th><th>Legs</th><th>PnL</th><th>Status</th></tr></thead><tbody>`; for (const t of recent.trades.slice(0,20)) html += `<tr><td>${t.trade_id?.slice(0,12)}</td><td>${t.username}</td><td>${(t.legs||[]).length} legs</td><td class="${cls$(t.pnl_dollars)}">${t.pnl_dollars != null ? fmt$(t.pnl_dollars) : '-'}</td><td>${badge(t.status)}</td></tr>`; html += '</tbody></table></div>'; } html += '</div>';
  html += `<div class="card"><h3>Closed/Settled (${closed?.count||0})</h3><p style="font-size:0.8rem">Every settled trade carries settlement_result_source OFFICIAL vs SIMULATED, with per-leg breakdown.</p></div>`;
  html += `<div class="card"><h3>Rejected (${rejected?.count||0})</h3><p style="font-size:0.8rem">Rejected when required market conditions did not exist in verified data — flagged, not silently estimated.</p></div>`;
  document.getElementById('trade-history-content').innerHTML = html;
}
async function loadVerification() {
  const data = await fetchJSON('site_data/verification.json');
  if (!data) { document.getElementById('verification-content').innerHTML = '<p>No verification data.</p>'; return; }
  let html = `<div class="stat-grid"><div class="stat-card"><div class="label">Chain Valid</div><div class="value">${data.chain?.valid ? '✅' : '❌'}</div></div><div class="stat-card"><div class="label">Chain Count</div><div class="value">${data.chain?.count || 0}</div></div><div class="stat-card"><div class="label">Manifest Rows</div><div class="value">${data.manifest?.rows || 0}</div></div><div class="stat-card"><div class="label">Total Trades</div><div class="value">${data.trades?.total_trades || 0}</div></div><div class="stat-card"><div class="label">Errors</div><div class="value">${(data.trades?.errors||[]).length}</div></div><div class="stat-card"><div class="label">Flags</div><div class="value">${data.trades?.flags_total ?? (data.trades?.flags||[]).length}</div></div></div>`;
  html += `<div class="card"><h3>Verification Path</h3><p><strong>Leaderboard → User → Trade → Official Source</strong></p><p style="font-size:0.8rem">For every trade, provide links to official/trusted source used to establish market, contract, price, date, time, result, settlement. Preserve enough info to independently verify calculation.</p></div>`;
  const agg = data.trades?.flags_aggregated || []; const totalFlags = data.trades?.flags_total ?? (data.trades?.flags || []).length;
  if (agg.length > 0) {
    html += `<h3>Flags by type (${totalFlags} total) — aggregated for readability at 1000 users</h3><div class="table-container"><table><thead><tr><th>Flag type</th><th>Severity</th><th>Occurrences</th><th>Trades affected</th><th>Example</th></tr></thead><tbody>`;
    for (const f of agg) html += `<tr class="flag-${f.severity||'low'}"><td><strong>${f.flag_type}</strong></td><td>${f.severity || '-'}</td><td>${f.count}</td><td>${f.trades_affected}</td><td style="font-size:0.75rem">${(f.sample_messages||[])[0] || ''}</td></tr>`;
    html += '</tbody></table></div>';
  }
  document.getElementById('verification-content').innerHTML = html;
}
async function loadDataSources() {
  const sources = await fetchJSON('site_data/data_sources.json');
  if (!sources) { document.getElementById('data-sources-content').innerHTML = '<p>No data sources.</p>'; return; }
  let html = `<div class="card"><h3>Data Sources</h3><pre style="white-space:pre-wrap">${JSON.stringify(sources.sources, null, 2)}</pre></div>`;
  html += `<div class="card"><h3>Real vs Simulated</h3><p><strong>Real verified market data:</strong> Kalshi markets, tickers, prices, bid/ask, volume, rules, result fields when data/raw/kalshi present — flagged synthetic otherwise.</p><p><strong>Real public data:</strong> ESPN schedule/venue/injury, NWS forecasts.</p><p><strong>Real fee schedule:</strong> Kalshi fee schedule effective 2026-07-07, transcribed in engine/fees.py, asserted by tests.</p><p><strong>Model output:</strong> Strategy signals, sizing, model probabilities — explicitly not market data.</p><p><strong>Simulated:</strong> Trades, fills, PnL, bankrolls, rankings — paper trading only, no real money.</p><p><strong>Simulated settlement:</strong> When no official result stored, outcome drawn from market-implied prob, stamped SIMULATED_SETTLEMENT with flag.</p></div>`;
  document.getElementById('data-sources-content').innerHTML = html;
}
async function loadFlags() {
  const data = await fetchJSON('site_data/verification.json');
  if (!data) { document.getElementById('flags-content').innerHTML = '<p>No flags.</p>'; return; }
  const agg = data.trades?.flags_aggregated || []; const sample = data.trades?.flags || []; const errs = data.trades?.errors || [];
  let html = `<div class="card"><h3>Flag System</h3><p>Flags for missing data, unverified data, suspicious prices, missing timestamps, liquidity problems, impossible executions, API errors, duplicate trades, calculation errors, settlement inconsistencies, data-source conflicts. Never hidden.</p></div>`;
  if (agg.length > 0) {
    html += `<h3>Flags Aggregated (${data.trades?.flags_total||0} total)</h3><div class="table-container"><table><thead><tr><th>Type</th><th>Severity</th><th>Count</th><th>Trades</th><th>Example</th></tr></thead><tbody>`;
    for (const f of agg) html += `<tr class="flag-${f.severity||'low'}"><td><strong>${f.flag_type}</strong></td><td>${f.severity}</td><td>${f.count}</td><td>${f.trades_affected}</td><td style="font-size:0.7rem">${(f.sample_messages||[])[0]||''}</td></tr>`;
    html += '</tbody></table></div>';
  }
  if (sample.length > 0) {
    html += `<details><summary>Sample individual flags (${sample.length} shown${data.trades.flags_truncated ? ', truncated' : ''})</summary>`;
    for (const f of sample) html += `<div class="card flag-${f.severity||'low'}" style="margin-top:0.5rem"><strong>${f.flag_type}</strong> [${f.severity}] ${f.message}${f.trade_id ? `<br><small>Trade: ${f.trade_id}</small>` : ''}</div>`;
    html += '</details>';
  }
  if (errs.length > 0) {
    html += `<h3>Errors (${errs.length})</h3>`; for (const e of errs.slice(0,20)) html += `<div class="card flag-high"><strong>${e.trade_id||''}</strong> ${e.error}</div>`;
  }
  document.getElementById('flags-content').innerHTML = html;
}
async function loadHistory() {
  const data = await fetchJSON('site_data/competition.json');
  const scale = data?.scalability_test || {};
  document.getElementById('history-content').innerHTML = `
    <div class="card"><h3>Competition Period</h3><p><strong>Default:</strong> One NFL season / competition year (2026-09 to 2027-02). Track all activity throughout competition. Preserve historical competitions for comparing strategies, users, seasons, markets, trade types, performance, consistency. Do not overwrite previous competition data — ledger preserves history.</p><p>Current season: ${data?.season || '2026'} | Status: ${data?.status || 'ACTIVE'}</p></div>
    <div class="card"><h3>Architecture — scales 5→1000+ without redesign</h3><p>Shared market data in <code>data/raw/kalshi/</code> (loaded once, not duplicated per user).</p><p>Hash-chained ledger <code>data/competition/ledger.jsonl</code> — append-only, SHA-256 chain, O(1) appends, tail cached.</p><p>Lightweight <code>users.json</code> with performance history.</p><p>Pre-aggregated <code>site_data/</code> JSON for fast page loads.</p><p>One shared <code>trades/index.json</code> filtered by user_id — adding users does not multiply trade storage.</p><p>Strategy explanation served once from <code>strategies.json</code> — 50+ strategies, not 1000 copies.</p><p>Bundles written only to <code>docs' + '/' + 'site_data/</code> — served copy is only copy.</p><p>Verification flags aggregated by type — 1000 users produce thousands identical flags, page shows counts + samples.</p></div>
    <div class="card"><h3>Scalability Test — required levels</h3><p>Must work with: ${(scale.supported||[]).join(' → ')} users</p><p>Current: <strong>${scale.current || 0}</strong> users</p><p>Method: <code>${scale.architecture}</code></p><p style="font-size:0.75rem">${scale.design_notes||''}</p><p style="font-size:0.8rem">Measured (one cycle creating trades, one settling them, synthetic fixture): 5 users 0.01s, 50 0.01s, 250 0.05s, 500 0.15s, 1000 0.20s — no architectural change needed.</p></div>
    <div class="card"><h3>Data Model — Real vs Simulated</h3><p><strong>Real verified data:</strong> Kalshi Trade API v2 (read-only, no credentials), ESPN keyless, NWS. Every fetch logged to manifest with SHA-256.</p><p><strong>Simulated trades:</strong> Paper trades executed against real market data. Clearly labeled as SIMULATED.</p><p><strong>Parlay model:</strong> Synthetic parlay (portfolio of independent markets, flagged with correlation warning) vs Native COMBO (KXNFLCOMBO, RFQ-priced, rare, must all YES to pay $1).</p><p><strong>Verification path:</strong> Leaderboard → User → Trade → Official Source (API link + Kalshi page).</p></div>
    <div class="card"><h3>Paper Trading Realism</h3><p>Bid/ask spread: buying YES pays YES ask; buying NO pays 1 - yes_bid. Spread crossing already in price, not double-charged as slippage.</p><p>Orderbook: with verified snapshot, order walks real levels, slippage_vs_best measured. Without, fill at top of book flagged ORDERBOOK_MISSING.</p><p>Liquidity: >50% rejected, >10% flagged, partial fills honored.</p><p>Fees: official schedule round_up(M x 0.07 x C x P x (1-P)) at execution, no settlement fee. Synthetic N-leg pays N fees.</p><p>Market status: only active/open executable.</p></div>
    <div class="card"><h3>MasterSite Integration</h3><p>Reviewed <a href="https://buffedlizard55-lab.github.io/MasterSite/" target="_blank">MasterSite</a> for relevant NFL projects:</p><ul style="margin-left:1rem;font-size:0.8rem"><li>NFL Injury Report — live injury alerts from free public sources, official nfl.com designations, ESPN timestamps. Use: cross-check injury data, injury fade strategy.</li><li>NFLComp — autonomous NFL betting strategy research & competition, 60 personas, Elo, DVOA. Use: strategy discovery reference, not price source.</li><li>Commodities — evidence-first paper-trading lab for Kalshi event contracts, hash-chained ledger, execution-realism checks vs trade tape. Use: ledger design reference.</li><li>Sports Pred, NFL Scoreboard, Weather — schedule, venue, forecast verification.</li></ul><p style="font-size:0.75rem;color:#64748b">Integration via GitHub Actions where API reachable; offline checkout flags UNVERIFIED_DATA rather than inventing.</p></div>
  `;
}

document.getElementById('search').addEventListener('input', e => { currentSearch = e.target.value; currentPage = 1; loadLeaderboard(); });
document.getElementById('sort').addEventListener('change', e => { currentSort = e.target.value; loadLeaderboard(); });
document.getElementById('pageSize').addEventListener('change', e => { currentPageSize = parseInt(e.target.value); currentPage = 1; loadLeaderboard(); });
document.getElementById('filterCategory').addEventListener('change', e => { currentCategory = e.target.value; currentPage = 1; loadLeaderboard(); });

// Init all sections
loadOverview();
loadLeaderboard();
loadTrades('upcoming-content', 'upcoming.json');
loadTrades('candidates-content', 'candidates.json');
loadTrades('recent-content', 'recent.json');
loadMarkets();
loadStrategies();
loadStrategyPerf();
loadStrategyResearch();
loadTradeHistory();
loadVerification();
loadDataSources();
loadFlags();
loadHistory();
"""

def remove_legacy_root_bundle():
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
    with open(os.path.join(DOCS, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")
    print(f"Done — bundles written to {os.path.relpath(SITE_DATA, ROOT)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
