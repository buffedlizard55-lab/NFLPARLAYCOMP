#!/usr/bin/env python3
"""
Execution simulator for realistic paper trading.

Accounts for:
- Bid/ask spread
- Available liquidity
- Position size vs market depth
- Slippage
- Price movement
- Order availability
- Market status
- Contract settlement
- Trading fees

A simulated trade only executable when required market conditions existed per verified data.
If required info unavailable, flag limitation instead of inventing.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Tuple

from .utils import iso_now, make_flag, safe_float, safe_int

KALSHI_FEE_RATE = 0.07
MIN_LIQUIDITY = 10.0  # minimum $ liquidity to consider executable
MAX_SLIPPAGE_BPS = 100  # 1% max slippage assumption
DEFAULT_SLIPPAGE_BPS = 10  # 0.10%

def check_market_executable(market: Dict[str, Any], leg: Dict[str, Any],
                            quantity: int, side: str) -> Tuple[bool, List[dict], dict]:
    """Check if a leg is executable given market snapshot."""
    flags = []
    details = {}

    if not market:
        flags.append(make_flag("MISSING_DATA", f"Market {leg.get('market_ticker')} not in verified data", severity="high"))
        return False, flags, details

    status = market.get("status", "unknown")
    if status not in ("active", "open"):
        flags.append(make_flag("IMPOSSIBLE_EXECUTION", f"Market status {status} not executable for {leg.get('market_ticker')}", severity="high"))
        return False, flags, details

    # Liquidity check
    liquidity = safe_float(market.get("liquidity") or market.get("volume") or market.get("open_interest"), 0)
    volume_24h = safe_float(market.get("volume_24h"), 0)
    if liquidity is not None and liquidity < MIN_LIQUIDITY:
        flags.append(make_flag("LIQUIDITY_PROBLEM", f"Low liquidity ${liquidity} for {leg.get('market_ticker')}", severity="medium"))

    # Position size vs liquidity: don't allow >10% of liquidity
    entry_price = safe_float(leg.get("entry_price"), 0.5)
    notional = entry_price * quantity
    if liquidity and liquidity > 0 and notional > liquidity * 0.10:
        flags.append(make_flag("LIQUIDITY_PROBLEM", f"Position ${notional} >10% of liquidity ${liquidity} for {leg.get('market_ticker')}", severity="medium"))
        # Reduce quantity or reject if >50%
        if notional > liquidity * 0.50:
            flags.append(make_flag("IMPOSSIBLE_EXECUTION", f"Position too large vs liquidity", severity="high"))
            return False, flags, details

    # Bid/ask check
    yes_bid = safe_float(market.get("yes_bid"))
    yes_ask = safe_float(market.get("yes_ask"))
    last_price = safe_float(market.get("last_price"))

    if yes_bid is None and yes_ask is None and last_price is None:
        flags.append(make_flag("ORDERBOOK_MISSING", f"No bid/ask/last for {leg.get('market_ticker')}", severity="medium"))
        # Allow with slippage assumption flagged
        details["slippage_bps"] = DEFAULT_SLIPPAGE_BPS * 2
    else:
        # Calculate spread
        if yes_bid is not None and yes_ask is not None:
            spread = abs(yes_ask - yes_bid)
            details["spread"] = spread
            details["bid"] = yes_bid
            details["ask"] = yes_ask
            if spread > 0.10:
                flags.append(make_flag("LIQUIDITY_PROBLEM", f"Wide spread {spread:.2%} for {leg.get('market_ticker')}", severity="low"))
            # Execution price: if side YES, we pay ask; if NO, we pay 1-ask? Actually NO price = 1 - YES price
            # For YES side: buy YES at ask
            # For NO side: buy NO at ask for NO, which is 1 - YES bid? Simplify: use ask for same side
            if side == "YES":
                exec_price = yes_ask if yes_ask is not None else last_price
            else:
                # NO side: NO ask = 1 - YES bid (approx)
                # If NO orderbook not given, estimate
                no_ask = safe_float(market.get("no_ask"))
                if no_ask is not None:
                    exec_price = no_ask
                else:
                    exec_price = 1.0 - (yes_bid if yes_bid is not None else 0.5)
            details["exec_price"] = exec_price
            # Slippage based on spread
            details["slippage_bps"] = int(min(MAX_SLIPPAGE_BPS, max(DEFAULT_SLIPPAGE_BPS, spread * 10000 * 0.5)))
        else:
            # Only last price available
            details["exec_price"] = last_price
            details["slippage_bps"] = DEFAULT_SLIPPAGE_BPS

    # Check close time
    close_time = market.get("close_time") or market.get("expiration_time")
    if close_time:
        # If market already closed, not executable
        # We need current time context; for now, if status closed/settled, already rejected
        pass

    return True, flags, details

def simulate_execution(trade: Dict[str, Any], market_snapshots: Dict[str, Dict],
                       orderbook_snapshots: Dict[str, Dict] | None = None) -> Dict[str, Any]:
    """Simulate execution of a trade (single or parlay).

    Returns updated trade dict with execution fields and flags.
    """
    legs = trade.get("legs", [])
    if not legs:
        return {
            **trade,
            "status": "REJECTED",
            "result": "REJECTED",
            "flags": trade.get("flags", []) + [make_flag("CALCULATION_ERROR", "No legs in trade")],
        }

    all_flags = list(trade.get("flags", []))
    executable = True
    total_cost = 0.0
    total_slippage = 0.0
    exec_prices = []

    for leg in legs:
        ticker = leg.get("market_ticker")
        market = market_snapshots.get(ticker)
        if not market and orderbook_snapshots:
            # Try orderbook snapshot
            ob = orderbook_snapshots.get(ticker)
            if ob:
                market = ob.get("book", {}).get("market") or ob.get("market") or {}
                # Merge orderbook fields
                if "orderbook" in ob:
                    market = {**market, **ob["orderbook"]}

        side = leg.get("side", "YES")
        quantity = safe_int(leg.get("quantity"), 1)

        ok, flags, details = check_market_executable(market or {}, leg, quantity, side)
        all_flags.extend(flags)
        if not ok:
            executable = False

        exec_price = details.get("exec_price") or safe_float(leg.get("entry_price"), 0.5)
        slippage_bps = details.get("slippage_bps", DEFAULT_SLIPPAGE_BPS)
        slippage = exec_price * slippage_bps / 10000.0 * quantity

        total_cost += exec_price * quantity
        total_slippage += slippage
        exec_prices.append(exec_price)

        # Update leg with execution details
        leg["exec_price"] = exec_price
        leg["slippage"] = slippage
        leg["bid_at_entry"] = details.get("bid")
        leg["ask_at_entry"] = details.get("ask")
        leg["spread"] = details.get("spread")

    if not executable:
        return {
            **trade,
            "status": "REJECTED",
            "result": "REJECTED",
            "flags": all_flags,
            "why_exited": "Rejected by execution simulator due to market conditions",
        }

    # Combined price for parlay: product of exec prices (synthetic) or single price
    if len(exec_prices) == 1:
        combined_price = exec_prices[0]
    else:
        # Product for synthetic parlay
        combined_price = 1.0
        for p in exec_prices:
            combined_price *= p

    # Fees: 7% of profit potential (if wins) or 0 if loses? Actually fee on profit at settlement, but we estimate
    # For entry, fee is 0; fee only on profit. So we store estimated fee for win case
    quantity = safe_int(legs[0].get("quantity"), 1) if legs else 1
    fee_if_win = max(0.0, (1.0 - combined_price) * quantity * KALSHI_FEE_RATE)

    # Update trade
    updated = {
        **trade,
        "status": "EXECUTED",
        "result": "PENDING",
        "entry_price_combined": round(combined_price, 4),
        "position_size_dollars": round(total_cost, 4),
        "slippage_assumed": round(total_slippage, 4),
        "fees": round(fee_if_win, 4),
        "flags": all_flags,
        "updated_at": iso_now(),
    }

    # Add verification sources
    sources = []
    for leg in legs:
        ticker = leg.get("market_ticker")
        sources.append(f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}")
        sources.append(f"https://kalshi.com/markets/{ticker}")
    updated["official_sources"] = list(set(sources + updated.get("official_sources", [])))

    return updated

def simulate_close(trade: Dict[str, Any], market_snapshots: Dict[str, Dict],
                   exit_reason: str = "Manual close") -> Dict[str, Any]:
    """Simulate closing an open trade (selling before settlement)."""
    if trade.get("status") not in ("EXECUTED", "ORDER"):
        return trade

    # Find current market prices for exit
    exit_prices = []
    all_flags = list(trade.get("flags", []))
    for leg in trade.get("legs", []):
        ticker = leg.get("market_ticker")
        market = market_snapshots.get(ticker, {})
        last = safe_float(market.get("last_price") or market.get("yes_bid") or leg.get("exec_price"), 0.5)
        exit_prices.append(last)

    if len(exit_prices) == 1:
        combined_exit = exit_prices[0]
    else:
        combined_exit = 1.0
        for p in exit_prices:
            combined_exit *= p

    entry_combined = safe_float(trade.get("entry_price_combined"), 0.5)
    quantity = safe_int(trade.get("legs", [{}])[0].get("quantity"), 1)
    pnl = (combined_exit - entry_combined) * quantity - trade.get("fees", 0) - trade.get("slippage_assumed", 0)
    roi = (pnl / (entry_combined * quantity)) * 100 if entry_combined and quantity else 0

    return {
        **trade,
        "status": "CLOSED",
        "exit_price_combined": round(combined_exit, 4),
        "exit_timestamp": iso_now(),
        "pnl_dollars": round(pnl, 4),
        "roi_percent": round(roi, 2),
        "result": "WIN" if pnl > 0 else "LOSS",
        "why_exited": exit_reason,
        "flags": all_flags,
        "updated_at": iso_now(),
    }

def simulate_settlement(trade: Dict[str, Any], market_results: Dict[str, str]) -> Dict[str, Any]:
    """Settle trade based on official market results."""
    if trade.get("status") in ("SETTLED", "CANCELLED", "REJECTED"):
        return trade

    from .parlay import settle_parlay
    settlement = settle_parlay(trade, market_results)
    if settlement.get("status") == "PENDING":
        # Results not yet available
        return trade

    all_flags = list(trade.get("flags", []))
    # Check for settlement inconsistency
    for leg in trade.get("legs", []):
        ticker = leg.get("market_ticker")
        result = market_results.get(ticker)
        if result is None:
            all_flags.append(make_flag("SETTLEMENT_INCONSISTENCY", f"Missing settlement for {ticker}", severity="medium"))

    return {
        **trade,
        "status": "SETTLED",
        "settlement_price": settlement.get("settlement_price"),
        "pnl_dollars": settlement.get("pnl_dollars"),
        "roi_percent": settlement.get("roi_percent"),
        "result": settlement.get("result"),
        "exit_timestamp": iso_now(),
        "why_exited": f"Settled: {settlement.get('result')}",
        "flags": all_flags,
        "updated_at": iso_now(),
    }
