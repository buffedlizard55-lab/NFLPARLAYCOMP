#!/usr/bin/env python3
"""
Competition runner: simulates many users/strategies competing.

Scales 5 -> 1000+ users without redesign:
- Shared market data (data/raw/kalshi) loaded once
- Users are lightweight JSON (data/competition/users.json)
- Trades are hash-chained ledger (data/competition/ledger.jsonl)
- No per-user duplication of market data
- Ledger is read once per cycle and cached in memory

Each user:
- unique username, unique strategy, description, bankroll, open/closed trades, PnL, ROI, win/loss, etc.

Competition period: one NFL season (2026), but preserves history.
"""
from __future__ import annotations

import json
import os
import random
import time
import uuid
from typing import Any, Dict, List

from .utils import iso_now, make_flag, safe_float, safe_int, kelly_fraction
from .strategies import get_all_strategies, STRATEGY_REGISTRY
from .data_model import User, Trade
from .ledger import append_trade, read_ledger, get_trades_by_user, clear_ledger
from .execution import simulate_execution, simulate_settlement, simulate_close
from .nfl_data import load_schedule, load_injuries, load_weather

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMP_DIR = os.path.join(ROOT, "data", "competition")
RAW_KALSHI = os.path.join(ROOT, "data", "raw", "kalshi")

def ensure_comp_dir():
    os.makedirs(COMP_DIR, exist_ok=True)

def load_markets_shared() -> Dict[str, Any]:
    """Load shared market data efficiently (not duplicated per user)."""
    markets = []
    by_ticker = {}
    flags = []
    season_path = os.path.join(RAW_KALSHI, "season_events.json")
    if os.path.exists(season_path):
        try:
            with open(season_path, "r", encoding="utf-8") as f:
                season = json.load(f)
            markets_dir = os.path.join(RAW_KALSHI, "markets")
            for event_ticker in season.get("event_tickers", [])[:100]:
                path = os.path.join(markets_dir, f"{event_ticker}.json")
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as pf:
                        payload = json.load(pf)
                        for m in payload.get("markets", []):
                            markets.append(m)
                            by_ticker[m["ticker"]] = m
                except:
                    continue
        except Exception as e:
            flags.append(make_flag("API_ERROR", f"Failed loading season_events: {e}", severity="low"))
    else:
        flags.append(make_flag("MISSING_DATA",
                               "No season_events.json, using synthetic fixtures flagged as UNVERIFIED for offline testing",
                               severity="medium"))

    # If no real data, create synthetic fixture markets for offline testing (flagged as synthetic)
    if not markets:
        synthetic = []
        teams = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
                 "DET", "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA",
                 "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF", "SEA", "TB", "TEN", "WAS"]
        # Deterministic seed for reproducibility
        rng = random.Random(42)
        for i in range(50):
            away = rng.choice(teams)
            home = rng.choice([t for t in teams if t != away])
            event_ticker = f"KXNFLGAME-26SEP{20 + i % 10:02d}{away}{home}"
            for series, suffix in [("KXNFLGAME", f"-{home}"),
                                   ("KXNFLSPREAD", f"-{home}-3.5"),
                                   ("KXNFLTOTAL", f"-O45.5"),
                                   ("KXNFLTEAMTOTAL", f"-{home}-O22.5"),
                                   ("KXNFL1H", f"-{home}"),
                                   ("KXNFL1QTOTAL", f"-O10.5")]:
                ticker = f"{series}-{event_ticker.split('-', 1)[1]}{suffix}"
                m = {
                    "ticker": ticker,
                    "event_ticker": event_ticker,
                    "series_ticker": series,
                    "status": "active",
                    "title": f"{away} vs {home}",
                    "subtitle": f"{series}",
                    "yes_bid": round(rng.uniform(0.4, 0.7), 2),
                    "yes_ask": round(rng.uniform(0.41, 0.71), 2),
                    "last_price": round(rng.uniform(0.4, 0.7), 2),
                    "volume": rng.uniform(1000, 50000),
                    "volume_24h": rng.uniform(500, 20000),
                    "open_interest": rng.uniform(1000, 30000),
                    "liquidity": rng.uniform(500, 20000),
                    "open_time": "2026-09-01T00:00:00Z",
                    "close_time": "2026-09-27T20:00:00Z",
                    "expiration_time": "2026-09-27T20:00:00Z",
                    "result": None,
                }
                synthetic.append(m)
                by_ticker[ticker] = m
        markets = synthetic
        flags.append(make_flag("UNVERIFIED_DATA",
                               "Using synthetic fixture markets for offline testing (no real Kalshi data). "
                               "Flagged as synthetic, not real verified data.",
                               severity="low"))

    return {"markets": markets, "by_ticker": by_ticker, "flags": flags}

def load_candles_shared() -> Dict[str, List[dict]]:
    candles_dir = os.path.join(RAW_KALSHI, "candles")
    out = {}
    if not os.path.exists(candles_dir):
        return out
    for series in os.listdir(candles_dir):
        series_path = os.path.join(candles_dir, series)
        if not os.path.isdir(series_path):
            continue
        for fn in os.listdir(series_path)[:100]:
            fp = os.path.join(series_path, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                    ticker = payload.get("ticker")
                    bars = payload.get("bars", [])
                    if ticker and bars:
                        out[ticker] = bars
            except:
                continue
    return out

def generate_usernames(n: int, seed: int = 42) -> List[str]:
    """Generate unique, deterministic usernames."""
    rng = random.Random(seed)
    adjectives = [
        "Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Sharp", "Quant",
        "Value", "Momentum", "Contrarian", "Weather", "Injury", "Home", "Road",
        "Primetime", "Divisional", "Rookie", "Veteran", "Elo", "Dvoa", "Arb",
        "Liquidity", "Parlay", "Combo", "Under", "Over", "Spread", "Moneyline",
        "Total", "Prop", "TD", "First", "Second", "Blowout", "Streak", "Coach",
        "Rivalry", "Iron", "Steel", "Titan", "Neutron", "Proton", "Photon",
        "Quark", "Pulse", "Vector", "Scalar", "Matrix", "Tensor", "Cipher",
        "Apex", "Bolt", "Crest", "Drift", "Edge", "Flux", "Grid", "Hawk",
        "Ion", "Jet", "Knot", "Lynx", "Mesa", "Nex", "Orbit", "Peak",
        "Ridge", "Surge", "Tide", "Ultra", "Viper", "Wave", "Xeno", "Yield",
        "Zenith", "Aura", "Blaze", "Core", "Dash", "Echo", "Forge", "Glow",
        "Haze", "Iris", "Jade", "Kite", "Link", "Mist", "Node", "Opal",
        "Plume", "Quill", "Rune", "Sage", "Torch", "Unity", "Vale", "Wren",
    ]
    nouns = [
        "Trader", "Bettor", "Model", "System", "Edge", "Signal", "Wolf", "Shark",
        "Lion", "Eagle", "Hawk", "Falcon", "TraderX", "QuantX", "AlphaX", "BetaX",
        "GammaX", "DeltaX", "Sigma", "Theta", "Vega", "Rho", "Kappa", "Lambda",
        "Zeta", "Omega", "Strike", "Forge", "Anvil", "Comet", "Dart", "Flame",
        "Glide", "Jet", "Kite", "Loop", "Mesh", "Nova", "Opal", "Pike",
        "Rune", "Spear", "Talon", "Vortex", "Whirl", "Yoke", "Zone", "Arc",
        "Bolt", "Crest", "Drum", "Echo", "Fang", "Grit", "Helm", "Ion",
        "Jade", "Key", "Link", "Mace", "Nail", "Oak", "Pike", "Quartz",
        "Ridge", "Shard", "Torch", "Urn", "Vault", "Wand", "Xenon", "Yew",
        "Zinc", "Amber", "Brick", "Clay", "Dusk", "Ember", "Flint", "Glade",
        "Haven", "Iron", "Jasper", "Knot", "Loom", "Mesa", "Nexus", "Onyx",
    ]
    usernames = set()
    max_attempts = n * 10
    attempts = 0
    while len(usernames) < n and attempts < max_attempts:
        adj = rng.choice(adjectives)
        noun = rng.choice(nouns)
        num = rng.randint(1, 9999)
        uname = f"{adj}{noun}_{num}"
        usernames.add(uname)
        attempts += 1
    # If we still don't have enough, add numbered ones
    while len(usernames) < n:
        usernames.add(f"Trader_{len(usernames):04d}")
    return sorted(usernames)

def create_users(num_users: int, starting_bankroll: float = 10000.0, seed: int = 42) -> List[dict]:
    """Create N users with unique strategies.

    For up to len(strategies) users, each gets a distinct strategy.
    For more, we create meaningful variations: different bankrolls, position sizing,
    risk profiles, and market focuses drawn from the strategy pool.
    """
    rng = random.Random(seed)
    strategies = get_all_strategies()
    usernames = generate_usernames(num_users, seed)
    users = []

    for i in range(num_users):
        strat = strategies[i % len(strategies)]
        # For users beyond strategy count, create meaningful parameter variations
        if i >= len(strategies):
            # Vary bankroll, risk tolerance, market focus
            bankroll_mult = rng.uniform(0.7, 1.3)
            risk_profile = rng.choice(["conservative", "moderate", "aggressive"])
        else:
            bankroll_mult = rng.uniform(0.9, 1.1)
            risk_profile = rng.choice(["conservative", "moderate", "aggressive"])

        user_id = f"user_{i:04d}_{uuid.uuid4().hex[:6]}"
        username = usernames[i]
        bankroll = round(starting_bankroll * bankroll_mult, 2)

        # Build a unique explanation even for strategy variations
        variation_note = ""
        if i >= len(strategies):
            variation_note = (f" (variation #{i - len(strategies) + 1}: "
                              f"{risk_profile} sizing, ${bankroll:.0f} bankroll)")

        user = {
            "user_id": user_id,
            "username": username,
            "strategy_id": strat.strategy_id,
            "strategy_name": strat.name + (f" v{i}" if i >= len(strategies) else ""),
            "strategy_description": strat.description + variation_note,
            "strategy_long_explanation": strat.long_explanation,
            "starting_bankroll": bankroll,
            "current_bankroll": bankroll,
            "open_trades": [],
            "closed_trades": [],
            "total_pnl": 0.0,
            "roi_percent": 0.0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_trades": 0,
            "rank": None,
            "performance_history": [{"t": iso_now(), "bankroll": bankroll, "pnl": 0}],
            "explanation": f"User {username} uses {strat.name}: {strat.description}{variation_note}",
            "created_at": iso_now(),
            "last_trade_at": None,
            "competition_status": "ACTIVE",
            "flags": [],
            "risk_profile": risk_profile if i >= len(strategies) else "moderate",
        }
        users.append(user)
    return users

def save_users(users: List[dict]):
    ensure_comp_dir()
    path = os.path.join(COMP_DIR, "users.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"users": users, "updated_at": iso_now(), "count": len(users)}, f)

def load_users() -> List[dict]:
    path = os.path.join(COMP_DIR, "users.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("users", [])

def _build_trade_index(ledger: List[dict]) -> Dict[str, dict]:
    """Build a dict of trade_id -> latest trade record for O(1) lookup."""
    index = {}
    for t in ledger:
        tid = t.get("trade_id")
        if tid:
            index[tid] = t
    return index

def generate_candidate_trades(market_data: Dict[str, Any], context: Dict[str, Any],
                              users: List[dict], max_candidates_per_user: int = 2) -> List[dict]:
    """Generate CANDIDATE trades for upcoming analysis without execution.

    Each strategy continuously determines what NFL markets it wants to trade,
    why, proposed entry, current verified price, EV, position size, required
    liquidity, conditions, executability, invalidation.

    Returns list of candidate trade dicts (not yet appended to ledger).
    """
    candidates = []
    for user in users[:min(200, len(users))]:  # limit for efficiency, sample 200 users for upcoming view
        strat_id = user["strategy_id"]
        strategy = STRATEGY_REGISTRY.get(strat_id)
        if not strategy:
            continue
        try:
            signal = strategy.evaluate(market_data, context)
        except Exception:
            continue
        if not signal.get("signal"):
            continue
        legs_input = signal.get("legs", [])
        if not legs_input:
            continue
        # Build rich candidate record
        candidate_legs = []
        for leg_in in legs_input[:4]:
            ticker = leg_in["market_ticker"]
            market = market_data["by_ticker"].get(ticker)
            if not market:
                continue
            current_price = market.get("last_price") or market.get("yes_bid") or 0.5
            proposed_price = leg_in.get("entry_price") or current_price
            candidate_legs.append({
                "market_ticker": ticker,
                "event_ticker": market.get("event_ticker"),
                "series_ticker": market.get("series_ticker"),
                "contract": ticker,  # contract is ticker in Kalshi binary markets
                "side": leg_in.get("side", "YES"),
                "proposed_entry_price": proposed_price,
                "current_verified_price": current_price,
                "entry_timestamp": iso_now(),
                "expiration_date": market.get("expiration_time") or market.get("close_time"),
                "settlement_date": market.get("expiration_time"),
                "quantity": 1,
                "position_size": signal.get("position_size", 0.01),
                "implied_prob": current_price,
                "liquidity": market.get("liquidity"),
                "bid": market.get("yes_bid"),
                "ask": market.get("yes_ask"),
                "spread": round((market.get("yes_ask") or 0) - (market.get("yes_bid") or 0), 6) if market.get("yes_bid") and market.get("yes_ask") else None,
                "model_prob": leg_in.get("model_prob"),
                "reason": leg_in.get("reason"),
                "source_url": f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
                "verification_url": f"https://kalshi.com/markets/{ticker}",
            })
        if not candidate_legs:
            continue
        total_ev = signal.get("expected_value", 0)
        # Determine executability
        executable = True
        reasons = []
        for leg in candidate_legs:
            if leg["liquidity"] is not None and leg["liquidity"] < 100:
                executable = False
                reasons.append(f"Low liquidity {leg['market_ticker']}")
            if leg["spread"] is not None and leg["spread"] > 0.10:
                reasons.append(f"Wide spread {leg['market_ticker']}")
        candidate = {
            "trade_id": f"candidate_{uuid.uuid4().hex[:12]}",
            "user_id": user["user_id"],
            "username": user["username"],
            "strategy_id": strat_id,
            "strategy_name": user["strategy_name"],
            "status": "CANDIDATE",
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "legs": candidate_legs,
            "proposed_entry_price": sum(l["proposed_entry_price"] for l in candidate_legs) / len(candidate_legs) if candidate_legs else 0,
            "current_verified_price": sum(l["current_verified_price"] for l in candidate_legs) / len(candidate_legs) if candidate_legs else 0,
            "expected_value": total_ev,
            "position_size": signal.get("position_size", 0.01),
            "position_size_dollars": 0,
            "required_liquidity": sum((l["liquidity"] or 0) for l in candidate_legs),
            "conditions_required": signal.get("why_enter", ""),
            "avoid_conditions": signal.get("why_avoid", ""),
            "is_executable": executable,
            "invalidation_conditions": "Price moves >5c against, liquidity drops <100, market status changes from active",
            "why_entered": signal.get("why_enter", ""),
            "official_sources": [l["source_url"] for l in candidate_legs],
            "flags": signal.get("flags", []),
            "market_type": "SYNTHETIC_PARLAY" if len(candidate_legs) > 1 else "SINGLE",
        }
        candidates.append(candidate)
    return candidates

def save_upcoming_trades(candidates: List[dict]):
    """Save candidate trades to a separate file for site builder."""
    ensure_comp_dir()
    path = os.path.join(COMP_DIR, "upcoming_candidates.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": iso_now(), "count": len(candidates), "candidates": candidates[:500]}, f)

def run_competition_cycle(num_users: int | None = None, max_trades_per_user: int = 3,
                          starting_bankroll: float = 10000.0, clear: bool = False) -> dict:
    """Run one competition cycle: generate signals, simulate execution, update users.

    This is designed to be efficient for 1000 users:
    - Load shared market data once
    - Read ledger once, build in-memory index
    - Evaluate each strategy (lightweight)
    - Simulate execution (checks liquidity)
    - Append to hash-chained ledger
    - Update user bankrolls
    """
    ensure_comp_dir()
    if clear:
        clear_ledger()
        users_path = os.path.join(COMP_DIR, "users.json")
        if os.path.exists(users_path):
            os.remove(users_path)

    # Load or create users
    users = load_users()
    if num_users is not None and len(users) != num_users:
        users = create_users(num_users, starting_bankroll)
        save_users(users)
    elif not users:
        users = create_users(5, starting_bankroll)
        save_users(users)

    # Load shared data once
    market_data = load_markets_shared()
    candles = load_candles_shared()
    schedule = load_schedule()
    injuries = load_injuries()
    weather = load_weather()

    context = {
        "candles": candles,
        "schedule": schedule,
        "injuries": injuries,
        "weather": weather.get("games", {}),
        "timestamp": iso_now(),
    }

    # Load orderbooks if available
    orderbooks = {}
    orderbooks_dir = os.path.join(RAW_KALSHI, "orderbooks")
    if os.path.exists(orderbooks_dir):
        files = sorted(os.listdir(orderbooks_dir))
        if files:
            latest = os.path.join(orderbooks_dir, files[-1])
            try:
                with open(latest, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    orderbooks = data.get("books", {})
            except:
                pass

    # Read ledger once and build index for O(1) lookups
    full_ledger = read_ledger()
    trade_index = _build_trade_index(full_ledger)

    # Generate CANDIDATE trades for upcoming analysis (before execution)
    # This shows what every strategy wants to trade before simulated execution
    try:
        candidates = generate_candidate_trades(market_data, context, users)
        save_upcoming_trades(candidates)
    except Exception as e:
        candidates = []
        # Flag but don't fail cycle
        pass

    # For each user, evaluate strategy and generate trades
    trades_created = 0
    new_trades = []  # collect new trades to append after processing

    for user in users:
        strat_id = user["strategy_id"]
        strategy = STRATEGY_REGISTRY.get(strat_id)
        if not strategy:
            # Try base strategy for variations
            base_id = strat_id.split("_VAR")[0]
            strategy = STRATEGY_REGISTRY.get(base_id)
            if not strategy:
                continue

        # Evaluate strategy
        try:
            signal = strategy.evaluate(market_data, context)
        except Exception as e:
            user.setdefault("flags", []).append(
                make_flag("CALCULATION_ERROR", f"Strategy {strat_id} eval error: {e}", severity="low"))
            continue

        if not signal.get("signal"):
            continue

        legs_input = signal.get("legs", [])
        if not legs_input:
            continue

        # Limit open trades per user
        if len(user["open_trades"]) >= max_trades_per_user * 2:
            continue

        # Build trade legs with verification info
        trade_legs = []
        for leg_in in legs_input[:4]:  # max 4 legs per parlay
            ticker = leg_in["market_ticker"]
            market = market_data["by_ticker"].get(ticker)
            if not market:
                continue
            entry_price = leg_in.get("entry_price") or market.get("last_price") or 0.5
            pos_frac = signal.get("position_size", 0.01)
            quantity = max(1, int((user["current_bankroll"] * pos_frac) / max(0.01, entry_price)))

            trade_leg = {
                "market_ticker": ticker,
                "event_ticker": market.get("event_ticker"),
                "series_ticker": market.get("series_ticker"),
                "contract": ticker,  # Kalshi binary contract = ticker
                "side": leg_in.get("side", "YES"),
                "entry_price": entry_price,
                "entry_timestamp": iso_now(),
                "expiration_date": market.get("expiration_time") or market.get("close_time"),
                "settlement_date": market.get("expiration_time"),
                "close_time": market.get("close_time"),
                "open_time": market.get("open_time"),
                "quantity": quantity,
                "position_size": round(entry_price * quantity, 2),
                "implied_prob": entry_price,
                "liquidity_at_entry": market.get("liquidity"),
                "liquidity": market.get("liquidity"),
                "bid_at_entry": market.get("yes_bid"),
                "ask_at_entry": market.get("yes_ask"),
                "bid": market.get("yes_bid"),
                "ask": market.get("yes_ask"),
                "spread": round((market.get("yes_ask") or 0) - (market.get("yes_bid") or 0), 6) if market.get("yes_bid") and market.get("yes_ask") else None,
                "slippage_assumed": 0.0,
                "source_file": f"data/raw/kalshi/markets/{market.get('event_ticker')}.json",
                "source_sha256": "pending_manifest_lookup",
                "source_url": f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
                "verification_url": f"https://kalshi.com/markets/{ticker}",
                "official_source": f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
                "model_prob": leg_in.get("model_prob"),
                "reason": leg_in.get("reason"),
                "verification_info": {
                    "market_ticker": ticker,
                    "event_ticker": market.get("event_ticker"),
                    "series_ticker": market.get("series_ticker"),
                    "price_source": "Kalshi Trade API v2",
                    "timestamp_source": "entry_timestamp",
                    "liquidity_source": "market.liquidity field",
                },
            }
            trade_legs.append(trade_leg)

        if not trade_legs:
            continue

        # Position sizing: cap by bankroll
        total_notional = sum(l["entry_price"] * l["quantity"] for l in trade_legs)
        if total_notional > user["current_bankroll"] * 0.10:
            scale = (user["current_bankroll"] * 0.10) / total_notional if total_notional else 1
            for l in trade_legs:
                l["quantity"] = max(1, int(l["quantity"] * scale))
            total_notional = sum(l["entry_price"] * l["quantity"] for l in trade_legs)

        # Create trade record
        trade_id = f"trade_{uuid.uuid4().hex[:12]}"
        trade = {
            "trade_id": trade_id,
            "user_id": user["user_id"],
            "username": user["username"],
            "strategy_id": strat_id,
            "status": "SIGNAL",
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "legs": trade_legs,
            "position_size_dollars": round(total_notional, 2),
            "entry_price_combined": None,
            "exit_price_combined": None,
            "exit_timestamp": None,
            "settlement_price": None,
            "fees": 0.0,
            "slippage_assumed": 0.0,
            "pnl_dollars": None,
            "roi_percent": None,
            "result": "PENDING",
            "official_sources": [f"https://api.elections.kalshi.com/trade-api/v2/markets/{l['market_ticker']}" for l in trade_legs],
            "verification_notes": "",
            "flags": signal.get("flags", []),
            "prev_hash": None,
            "hash": None,
            "why_entered": signal.get("why_enter", ""),
            "why_exited": "",
            "expected_value": signal.get("expected_value"),
            "market_type": "SYNTHETIC_PARLAY" if len(trade_legs) > 1 else "SINGLE",
            "is_native_kalshi_combo": False,
        }

        # Lifecycle: SIGNAL -> ORDER -> simulate execution
        trade["status"] = "ORDER"
        executed = simulate_execution(trade, market_data["by_ticker"], orderbooks)

        if executed["status"] == "REJECTED":
            append_trade(executed)
            new_trades.append(executed)
            trades_created += 1
            continue

        # Deduct the full cash debit (cost + entry fees) from the bankroll.
        # `total_debit_dollars` is set by the execution simulator from the official
        # fee schedule; fall back to cost only when it is absent.
        debit = safe_float(executed.get("total_debit_dollars"),
                           safe_float(executed.get("position_size_dollars"), 0))
        user["current_bankroll"] = round(user["current_bankroll"] - debit, 2)
        user["open_trades"].append(trade_id)
        user["total_trades"] += 1
        user["last_trade_at"] = iso_now()

        # Append executed trade to ledger
        append_trade(executed)
        new_trades.append(executed)
        trades_created += 1

    # --- SETTLEMENT PHASE ---
    # 1) OFFICIAL results: read verbatim from Kalshi settled markets (the `result`
    #    field on GET /markets?event_ticker=... is the authoritative outcome).
    settled_results: Dict[str, str] = {}
    settlement_source: Dict[str, str] = {}
    markets_dir = os.path.join(RAW_KALSHI, "markets")
    if os.path.exists(markets_dir):
        for fn in os.listdir(markets_dir)[:50]:
            fp = os.path.join(markets_dir, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                    for m in payload.get("markets", []):
                        if m.get("status") == "settled" and m.get("result"):
                            settled_results[m["ticker"]] = m["result"]
                            settlement_source[m["ticker"]] = "OFFICIAL"
            except:
                continue

    # 2) FALLBACK: with no official results stored (e.g. offline or before the games
    #    have settled), draw an outcome from the market-implied probability so the
    #    competition still exercises its full lifecycle. This is a SIMULATION, not a
    #    result: every trade settled this way is stamped SIMULATED_SETTLEMENT and
    #    carries a flag, so it can never be mistaken for a verified outcome.
    simulated_settlements = not bool(settled_results)
    if simulated_settlements:
        rng = random.Random(int(time.time()) // 3600)  # hourly seed => reproducible within the hour
        for t in full_ledger + new_trades:
            if t.get("status") != "EXECUTED":
                continue
            for leg in t.get("legs", []):
                ticker = leg.get("market_ticker")
                if not ticker or ticker in settled_results:
                    continue
                price = safe_float(leg.get("entry_price") or leg.get("implied_prob"), 0.5)
                settled_results[ticker] = "yes" if rng.random() < price else "no"
                settlement_source[ticker] = "SIMULATED"

    # Settle trades using in-memory trade_index for O(1) lookups
    settled_count = 0
    for user in users:
        open_trades = list(user["open_trades"])
        for trade_id in open_trades:
            trade = trade_index.get(trade_id)
            if not trade:
                continue
            if trade["status"] != "EXECUTED":
                continue

            # Check if all legs have results
            if all(leg["market_ticker"] in settled_results for leg in trade["legs"]):
                settled = simulate_settlement(trade, settled_results)
                if settled["status"] == "SETTLED":
                    # Stamp provenance: a viewer must be able to tell, per leg and per
                    # trade, whether the outcome is an official Kalshi result or a draw.
                    leg_sources = {leg["market_ticker"]: settlement_source.get(
                        leg["market_ticker"], "UNKNOWN") for leg in trade.get("legs", [])}
                    if any(v == "SIMULATED" for v in leg_sources.values()):
                        overall = "SIMULATED" if all(
                            v == "SIMULATED" for v in leg_sources.values()) else "PARTIAL"
                        settled["settlement_result_source"] = overall
                        settled["settlement_leg_sources"] = leg_sources
                        settled["settlement_note"] = (
                            "Outcome drawn from market-implied probability because no official "
                            "Kalshi settlement was stored for these markets. This is a SIMULATION, "
                            "not a verified result.")
                        settled.setdefault("flags", []).append(make_flag(
                            "SIMULATED_SETTLEMENT",
                            "No official Kalshi settlement stored; result was simulated from the "
                            "market-implied probability rather than read from a settled market.",
                            trade_id=trade_id, severity="medium"))
                    else:
                        settled["settlement_result_source"] = "OFFICIAL"
                        settled["settlement_leg_sources"] = leg_sources
                        settled["settlement_note"] = ("Outcome read from the `result` field of the "
                                                      "settled Kalshi market.")
                    # Bankroll accounting (two cash flows, both explicit):
                    #   1. at execution : bankroll -= (cost + entry fee)   [done above]
                    #   2. at settlement: bankroll += payout ($1/contract if all legs win)
                    # Net effect = payout - cost - fee = pnl_dollars, so a trade's
                    # contribution to the bankroll is exactly its recorded PnL.
                    payout = safe_float(settled.get("payout_dollars"))
                    if payout is None:  # legacy records without the explicit field
                        pos_size = safe_float(settled.get("position_size_dollars"),
                                              safe_float(trade.get("position_size_dollars"), 0))
                        fees = safe_float(settled.get("fees"), 0)
                        pnl = safe_float(settled.get("pnl_dollars"), 0)
                        payout = pos_size + fees + pnl
                    pnl = safe_float(settled.get("pnl_dollars"), 0)

                    user["current_bankroll"] = round(user["current_bankroll"] + payout, 2)
                    user["total_pnl"] = round(user["total_pnl"] + pnl, 2)
                    if trade_id in user["open_trades"]:
                        user["open_trades"].remove(trade_id)
                    user["closed_trades"].append(trade_id)
                    if settled["result"] == "WIN":
                        user["wins"] += 1
                    else:
                        user["losses"] += 1
                    total = user["wins"] + user["losses"]
                    user["win_rate"] = round(user["wins"] / total * 100, 2) if total else 0
                    user["roi_percent"] = round(
                        (user["total_pnl"] / user["starting_bankroll"]) * 100, 2
                    ) if user["starting_bankroll"] else 0
                    user["performance_history"].append({
                        "t": iso_now(),
                        "bankroll": user["current_bankroll"],
                        "pnl": user["total_pnl"],
                    })

                    # Update the trade in our index and append settled version
                    append_trade(settled)
                    trade_index[trade_id] = settled
                    settled_count += 1

    # Update ranks
    users_sorted = sorted(users, key=lambda u: u["total_pnl"], reverse=True)
    for rank, u in enumerate(users_sorted, 1):
        u["rank"] = rank

    save_users(users_sorted)

    return {
        "users": len(users_sorted),
        "trades_created": trades_created,
        "settled": settled_count,
        "simulated_settlements": simulated_settlements,
        "market_flags": market_data.get("flags", []),
        "timestamp": iso_now(),
    }

def get_leaderboard(page: int = 1, page_size: int = 25, sort_by: str = "rank",
                    search: str | None = None) -> dict:
    users = load_users()
    if search:
        search_lower = search.lower()
        users = [u for u in users
                 if search_lower in u["username"].lower()
                 or search_lower in u["strategy_name"].lower()
                 or search_lower in u["strategy_id"].lower()]

    # Sorting
    sort_keys = {
        "pnl": lambda x: x["total_pnl"],
        "roi": lambda x: x["roi_percent"],
        "win_rate": lambda x: x["win_rate"],
        "trades": lambda x: x["total_trades"],
        "bankroll": lambda x: x["current_bankroll"],
    }
    if sort_by in sort_keys:
        users = sorted(users, key=sort_keys[sort_by], reverse=True)
    else:
        users = sorted(users, key=lambda x: x.get("rank") or 9999)

    total = len(users)
    start = (page - 1) * page_size
    end = start + page_size
    page_users = users[start:end]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "users": page_users,
    }
