#!/usr/bin/env python3
"""Execution simulator for realistic paper trading.

Models, using only verified snapshots:

* **Bid/ask spread** — a marketable order pays the quote on the side it takes.
  Buying YES pays the YES ask; buying NO pays the NO ask (`1 - yes_bid` when the
  market only publishes a YES book). Crossing the spread is therefore already in
  the price, and is NOT charged again as "slippage".
* **Book depth / slippage** — when a verified order-book snapshot is available the
  order walks real levels (engine/orderbook.py). When it is not, execution is capped
  at top-of-book and the shortfall is flagged rather than invented.
* **Liquidity** — position size is checked against available dollars; oversized
  orders are rejected (flagged IMPOSSIBLE_EXECUTION) rather than assumed filled.
* **Market status** — only `active`/`open` markets are executable.
* **Fees** — the official Kalshi schedule, charged ON EXECUTION per leg
  (`round up(M x 0.07 x C x P x (1-P))`), no settlement fee. See engine/fees.py.

Anything that cannot be established from stored data is flagged, never estimated
silently.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from .utils import iso_now, make_flag, safe_float, safe_int
from .fees import entry_fees, kalshi_fee
from .orderbook import walk_book, book_depth_dollars

MIN_LIQUIDITY = 10.0            # minimum $ liquidity to consider executable
MAX_FRACTION_OF_LIQUIDITY = 0.10  # flag above this share of visible liquidity
REJECT_FRACTION_OF_LIQUIDITY = 0.50  # reject above this share

# Our simulated orders are marketable (they cross the spread to reach the resting
# book), so they are TAkers and pay the published taker fee.
ORDER_TYPE = "taker"


def _top_of_book_price(market: dict, side: str) -> tuple[float | None, list[dict]]:
    """Best executable price for `side` from the quote fields, plus flags."""
    flags: list[dict] = []
    yes_bid = safe_float(market.get("yes_bid"))
    yes_ask = safe_float(market.get("yes_ask"))
    last = safe_float(market.get("last_price"))
    side = (side or "YES").upper()

    if side == "YES":
        if yes_ask is not None:
            return yes_ask, flags
        if last is not None:
            flags.append(make_flag(
                "ORDERBOOK_MISSING",
                "No YES ask in snapshot; falling back to last_price as the executable price",
                severity="medium"))
            return last, flags
        return None, flags

    # NO side: NO ask = 1 - YES bid. Use a published no_ask when present.
    no_ask = safe_float(market.get("no_ask"))
    if no_ask is not None:
        return no_ask, flags
    if yes_bid is not None:
        return round(1.0 - yes_bid, 6), flags
    if last is not None:
        flags.append(make_flag(
            "ORDERBOOK_MISSING",
            "No YES bid in snapshot; deriving NO price from last_price only",
            severity="medium"))
        return round(1.0 - last, 6), flags
    return None, flags


def check_market_executable(market: Dict[str, Any], leg: Dict[str, Any],
                            quantity: int, side: str,
                            book: Dict[str, Any] | None = None
                            ) -> Tuple[bool, List[dict], dict]:
    """Decide whether one leg can execute, and at what price.

    Returns (executable, flags, details) where details carries the modelled
    execution price, spread, depth and slippage figures actually used.
    """
    flags: List[dict] = []
    details: Dict[str, Any] = {}
    ticker = leg.get("market_ticker")

    if not market:
        flags.append(make_flag("MISSING_DATA",
                               f"Market {ticker} not in verified data", severity="high"))
        return False, flags, details

    status = market.get("status", "unknown")
    if status not in ("active", "open"):
        flags.append(make_flag("IMPOSSIBLE_EXECUTION",
                               f"Market status {status} not executable for {ticker}",
                               severity="high"))
        return False, flags, details

    side = (side or "YES").upper()
    quantity = max(0, int(quantity or 0))
    if quantity <= 0:
        flags.append(make_flag("CALCULATION_ERROR",
                               f"Non-positive quantity for {ticker}", severity="high"))
        return False, flags, details

    # --- price ---
    top_price, price_flags = _top_of_book_price(market, side)
    flags.extend(price_flags)
    if top_price is None or not (0.0 < top_price < 1.0):
        flags.append(make_flag("SUSPICIOUS_PRICE",
                               f"No usable price for {ticker} (side={side})", severity="high"))
        return False, flags, details

    details["top_of_book_price"] = round(top_price, 6)

    # --- book depth / slippage ---
    exec_price = top_price
    if book:
        fill = walk_book(book, side, quantity)
        if fill["filled_contracts"] <= 0:
            flags.append(make_flag("LIQUIDITY_PROBLEM",
                                   f"Order book for {ticker} has no levels on the {side} side",
                                   severity="high"))
            details["book"] = fill
            return False, flags, details
        if not fill["depth_sufficient"]:
            # Do not pretend the remainder filled.
            flags.append(make_flag(
                "LIQUIDITY_PROBLEM",
                f"Only {fill['filled_contracts']:.0f} of {quantity} contracts available on the "
                f"{side} side of {ticker}; remainder not executed",
                market_ticker=ticker, severity="high"))
        exec_price = fill["average_price"] or top_price
        details["book"] = fill
        details["slippage_vs_best"] = fill["slippage_vs_best"]
        details["filled_contracts"] = fill["filled_contracts"]
        details["fillable"] = fill["depth_sufficient"]
    else:
        # No snapshot book: top-of-book only. This is a documented limitation.
        details["slippage_vs_best"] = 0.0
        details["filled_contracts"] = float(quantity)
        details["fillable"] = True
        details["depth_modelled"] = False
        flags.append(make_flag(
            "ORDERBOOK_MISSING",
            f"No order-book snapshot for {ticker}: fill modelled at top of book only; "
            "depth-walking slippage not modelled for this trade",
            market_ticker=ticker, severity="low"))

    details["exec_price"] = round(exec_price, 6)

    # --- spread ---
    yes_bid = safe_float(market.get("yes_bid"))
    yes_ask = safe_float(market.get("yes_ask"))
    if yes_bid is not None and yes_ask is not None:
        spread = abs(yes_ask - yes_bid)
        details["spread"] = round(spread, 6)
        details["bid"] = yes_bid
        details["ask"] = yes_ask
        if spread > 0.10:
            flags.append(make_flag("LIQUIDITY_PROBLEM",
                                   f"Wide spread {spread:.2%} on {ticker}", severity="low"))
    else:
        details["spread"] = None

    # --- liquidity / size ---
    liquidity = safe_float(market.get("liquidity") or market.get("volume")
                           or market.get("open_interest"), 0) or 0.0
    notional = details["exec_price"] * quantity
    details["notional"] = round(notional, 6)
    if liquidity > 0:
        share = notional / liquidity
        details["share_of_liquidity"] = round(share, 6)
        if share > REJECT_FRACTION_OF_LIQUIDITY:
            flags.append(make_flag(
                "IMPOSSIBLE_EXECUTION",
                f"Position ${notional:.2f} is {share:.0%} of the ${liquidity:.2f} traded on "
                f"{ticker}; rejected as unexecutable",
                market_ticker=ticker, severity="high"))
            return False, flags, details
        if share > MAX_FRACTION_OF_LIQUIDITY:
            flags.append(make_flag(
                "LIQUIDITY_PROBLEM",
                f"Position ${notional:.2f} is {share:.0%} of the ${liquidity:.2f} traded on {ticker}",
                market_ticker=ticker, severity="medium"))
    elif liquidity < MIN_LIQUIDITY:
        flags.append(make_flag("LIQUIDITY_PROBLEM",
                               f"No usable liquidity figure for {ticker}", severity="medium"))

    return True, flags, details


def simulate_execution(trade: Dict[str, Any], market_snapshots: Dict[str, Dict],
                       orderbook_snapshots: Dict[str, Dict] | None = None) -> Dict[str, Any]:
    """Simulate execution of a trade (single market or synthetic multi-leg parlay).

    Every filled leg is charged its own taker fee from the official schedule. Partial
    depth shortfalls shrink the leg rather than being assumed away.
    """
    legs = trade.get("legs", [])
    if not legs:
        return {
            **trade,
            "status": "REJECTED",
            "result": "REJECTED",
            "flags": list(trade.get("flags", [])) + [
                make_flag("CALCULATION_ERROR", "No legs in trade")],
        }

    all_flags = list(trade.get("flags", []))
    executable = True
    total_cost = 0.0
    exec_prices: List[float] = []
    filled_quantities: List[int] = []

    for leg in legs:
        ticker = leg.get("market_ticker")
        market = market_snapshots.get(ticker)
        book = None
        if orderbook_snapshots:
            raw = orderbook_snapshots.get(ticker)
            if raw:
                book = raw.get("book") if "book" in raw else raw

        side = leg.get("side", "YES")
        quantity = safe_int(leg.get("quantity"), 1) or 1

        ok, flags, details = check_market_executable(market or {}, leg, quantity, side, book)
        all_flags.extend(flags)

        if not ok:
            executable = False
            # Keep whatever we learned so the rejected record is still auditable.
            leg["rejection_details"] = details
            continue

        # Honour a partial fill instead of assuming the whole order landed.
        filled = int(details.get("filled_contracts", quantity) or 0)
        filled = max(0, min(filled, quantity))
        if details.get("depth_modelled") is False:
            filled = quantity  # top-of-book model: no depth cap applies

        exec_price = details["exec_price"]
        cost = exec_price * filled

        total_cost += cost
        exec_prices.append(exec_price)
        filled_quantities.append(filled)

        leg["quantity_requested"] = quantity
        leg["quantity"] = filled
        leg["exec_price"] = exec_price
        leg["entry_price"] = exec_price      # the price actually received
        leg["bid_at_entry"] = details.get("bid")
        leg["ask_at_entry"] = details.get("ask")
        leg["spread"] = details.get("spread")
        leg["slippage_vs_best"] = details.get("slippage_vs_best")
        leg["execution_modelled_with_book"] = bool(book)
        if not details.get("fillable", True):
            all_flags.append(make_flag(
                "LIQUIDITY_PROBLEM",
                f"Partial fill on {ticker}: {filled} of {quantity} contracts",
                market_ticker=ticker, severity="high"))

    if not executable or not any(q > 0 for q in filled_quantities):
        return {
            **trade,
            "status": "REJECTED",
            "result": "REJECTED",
            "flags": all_flags,
            "why_exited": "Rejected by execution simulator: market conditions not met in verified data",
            "updated_at": iso_now(),
        }

    # Combined price for a synthetic parlay is the product of the leg prices; for a
    # single leg it is just that price. Native Kalshi combos are priced from their own
    # book elsewhere (see parlay.price_parlay_native_combo) and never reach this path.
    if len(exec_prices) == 1:
        combined_price = exec_prices[0]
    else:
        combined_price = math.prod(exec_prices)

    # Fees: charged per leg at execution, from the official schedule.
    fees = entry_fees(legs, maker=(ORDER_TYPE == "maker"))
    total_debit = total_cost + fees

    sources = []
    for leg in legs:
        ticker = leg.get("market_ticker")
        sources.append(f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}")
        sources.append(f"https://kalshi.com/markets/{ticker}")

    return {
        **trade,
        "status": "EXECUTED",
        "result": "PENDING",
        "entry_price_combined": round(combined_price, 6),
        "position_size_dollars": round(total_cost, 4),     # cost = price x contracts
        "entry_fees": round(fees, 6),
        "fees": round(fees, 6),
        "total_debit_dollars": round(total_debit, 4),      # cash leaving the account
        "order_type": ORDER_TYPE,
        "fee_model": ("round_up(M x 0.07 x C x P x (1-P)); Kalshi fee schedule "
                      "effective 2026-07-07; no settlement fee"),
        "slippage_assumed": round(sum(
            (leg.get("slippage_vs_best") or 0.0) * (leg.get("quantity") or 0)
            for leg in legs), 6),
        "flags": all_flags,
        "official_sources": sorted(set(sources + list(trade.get("official_sources", [])))),
        "updated_at": iso_now(),
    }


def simulate_close(trade: Dict[str, Any], market_snapshots: Dict[str, Dict],
                   exit_reason: str = "Manual close") -> Dict[str, Any]:
    """Close an open position before settlement (sell at the bid)."""
    if trade.get("status") not in ("EXECUTED", "ORDER"):
        return trade

    exit_prices: List[float] = []
    all_flags = list(trade.get("flags", []))
    for leg in trade.get("legs", []):
        ticker = leg.get("market_ticker")
        market = market_snapshots.get(ticker, {})
        side = (leg.get("side") or "YES").upper()
        # Selling means hitting the bid on our side.
        if side == "YES":
            bid = safe_float(market.get("yes_bid"))
        else:
            bid = safe_float(market.get("no_bid"))
            if bid is None:
                yes_ask = safe_float(market.get("yes_ask"))
                bid = round(1.0 - yes_ask, 6) if yes_ask is not None else None
        if bid is None:
            bid = safe_float(market.get("last_price") or leg.get("exec_price"))
            all_flags.append(make_flag(
                "ORDERBOOK_MISSING",
                f"No bid for {ticker} at exit; used last_price", severity="medium"))
        exit_prices.append(bid if bid is not None else 0.5)

    combined_exit = (exit_prices[0] if len(exit_prices) == 1
                     else math.prod(exit_prices))
    contracts = safe_float(trade.get("contracts")) or 0.0
    if not contracts:
        entry_combined = safe_float(trade.get("entry_price_combined"), 0) or 0
        cost = safe_float(trade.get("position_size_dollars"), 0) or 0
        contracts = (cost / entry_combined) if entry_combined else 0.0

    proceeds = combined_exit * contracts
    exit_fee = kalshi_fee(combined_exit, contracts) if contracts else 0.0
    cost = safe_float(trade.get("position_size_dollars"), 0) or 0.0
    entry_fee = safe_float(trade.get("fees"), 0) or 0.0
    pnl = proceeds - cost - entry_fee - exit_fee
    roi = (pnl / cost) * 100 if cost else 0.0

    return {
        **trade,
        "status": "CLOSED",
        "exit_price_combined": round(combined_exit, 6),
        "exit_timestamp": iso_now(),
        "exit_fees": round(exit_fee, 6),
        "fees": round(entry_fee + exit_fee, 6),
        "payout_dollars": round(proceeds, 4),
        "pnl_dollars": round(pnl, 4),
        "roi_percent": round(roi, 2),
        "result": "WIN" if pnl > 0 else "LOSS",
        "why_exited": exit_reason,
        "flags": all_flags,
        "updated_at": iso_now(),
    }


def simulate_settlement(trade: Dict[str, Any], market_results: Dict[str, str]) -> Dict[str, Any]:
    """Settle a trade from official market results. No settlement fee is charged."""
    if trade.get("status") in ("SETTLED", "CANCELLED", "REJECTED"):
        return trade

    from .parlay import settle_parlay
    settlement = settle_parlay(trade, market_results)
    if settlement.get("status") == "PENDING":
        return trade

    all_flags = list(trade.get("flags", []))
    for leg in trade.get("legs", []):
        ticker = leg.get("market_ticker")
        if market_results.get(ticker) is None:
            all_flags.append(make_flag("SETTLEMENT_INCONSISTENCY",
                                       f"Missing settlement for {ticker}", severity="medium"))

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
        # Cash-flow fields so the runner can reconcile the bankroll exactly:
        # cost + fees left the account at entry; payout returns now.
        "position_size_dollars": settlement.get("position_size_dollars",
                                                 safe_float(trade.get("position_size_dollars"), 0)),
        "fees": settlement.get("fees", safe_float(trade.get("fees"), 0)),
        "payout_dollars": settlement.get("payout_dollars"),
        "contracts": settlement.get("contracts"),
        "cash_out_dollars": settlement.get("cash_out_dollars"),
        "cash_in_dollars": settlement.get("cash_in_dollars"),
    }
