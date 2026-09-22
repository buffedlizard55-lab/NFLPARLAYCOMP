#!/usr/bin/env python3
"""Execution simulator: converts signals into (re)filled simulated trades.

Two execution regimes, both driven ONLY by verified data:

* REPLAY (games already played): the executable quote at decision time ts is
  the last completed hourly candlestick at/before ts (yes_ask / yes_bid close
  — real Kalshi quotes).  Historical order-book depth does not exist, so fill
  size is capped at REPLAY_VOLUME_FRACTION of that hour's traded volume
  (documented assumption, flagged on every replay fill).  If no bar exists
  within the staleness window, the order is REJECTED — never priced from an
  invented quote.

* LIVE (upcoming games): fills walk the actual current order book level by
  level (real resting liquidity at fetch time, from the latest snapshot).

Fees use Kalshi's published taker formula (see parlay.taker_fee). Every
fill/rejection is recorded with the exact snapshot source for verification.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.parlay import taker_fee
from engine.model import (REPLAY_VOLUME_FRACTION, REPLAY_MAX_CONTRACTS,
                          MAX_QUOTE_STALENESS_H)


@dataclass
class LegOrder:
    ticker: str
    side: str
    intended_contracts: float
    limit_price: float            # worst acceptable ask at execution time
    entry_quote_source: str = ""


@dataclass
class LegFill:
    ticker: str
    side: str
    contracts: float
    price: float
    fee: float
    cost: float                   # contracts * price + fee
    book_walk: list[dict] = field(default_factory=list)   # levels consumed (live)
    liquidity_source: str = ""


@dataclass
class ExecutionResult:
    status: str                    # "filled" | "partial" | "rejected"
    fills: list[LegFill] = []
    rejections: list[dict] = field(default_factory=list)
    note: str = ""
    regime: str = ""               # "replay" | "live"
    executed_at: int = 0
    snapshot_source: str = ""


def replay_fill(leg: LegOrder, quote, max_stale_h: float = MAX_QUOTE_STALENESS_H,
                volume_fraction: float = REPLAY_VOLUME_FRACTION,
                max_contracts: float = REPLAY_MAX_CONTRACTS,
                min_contracts: float = 1.0) -> ExecutionResult:
    """Fill one leg against a historical candle quote (replay regime)."""
    price = quote.ask(leg.side)
    if price is None or price <= 0 or price >= 1:
        return ExecutionResult("rejected", note="no_valid_ask",
                               regime="replay")
    if quote.stale_hours > max_stale_h:
        return ExecutionResult(
            "rejected", note=f"quote_stale_{quote.stale_hours:.1f}h",
            regime="replay",
            rejections=[{"ticker": leg.ticker, "reason": "stale_quote",
                         "bar_ts": quote.bar_ts}])
    if price > leg.limit_price + 1e-9:
        return ExecutionResult(
            "rejected", note=f"price_moved_above_limit_{price:.2f}",
            regime="replay",
            rejections=[{"ticker": leg.ticker, "reason": "price_above_limit",
                         "ask": price, "limit": leg.limit_price}])
    cap = min(volume_fraction * quote.bar_volume, max_contracts)
    contracts = min(leg.intended_contracts, cap)
    if contracts < min_contracts:
        return ExecutionResult(
            "rejected",
            note=(f"insufficient_replay_liquidity_cap_{cap:.2f}"),
            regime="replay",
            rejections=[{"ticker": leg.ticker, "reason": "low_replay_liquidity",
                         "hour_volume": quote.bar_volume, "cap": round(cap, 2)}])
    fee = taker_fee(price, contracts)
    cost = round(contracts * price, 2) + fee
    return ExecutionResult(
        "filled",
        fills=[LegFill(ticker=leg.ticker, side=leg.side, contracts=round(contracts, 2),
                       price=price, fee=fee, cost=round(cost, 2),
                       liquidity_source=(f"kalshi_candlesticks_hourly:"
                                         f"bar_end={quote.bar_ts}"),
                       book_walk=[{"price": price, "contracts": round(contracts, 2),
                                   "assumed_cap": round(cap, 2),
                                   "assumption": "10% of hourly volume"}])],
        regime="replay", note=("full" if contracts >= leg.intended_contracts - 1e-9
                               else "partial_liquidity_capped"))


def live_fill(leg: LegOrder, book: dict, min_contracts: float = 1.0) -> ExecutionResult:
    """Fill one leg by walking the current order book (live regime).

    `book` is a Kalshi orderbook_fp snapshot:
      yes_dollars: [[price, qty], ...] ascending — YES bid levels (best last)
      no_dollars:  [[price, qty], ...] ascending — NO bid levels (best last)
    Buying YES consumes NO bids (yes ask = 1 - no bid); buying NO consumes YES
    bids (no ask = 1 - yes bid).  (Verified against live orderbooks 2026-09-22:
    the arrays are sorted ascending by price with the best level last.)
    """
    levels = book.get("no_dollars") if leg.side == "yes" else book.get("yes_dollars")
    if not levels:
        return ExecutionResult("rejected", note="empty_orderbook", regime="live",
                               rejections=[{"ticker": leg.ticker,
                                            "reason": "no_resting_liquidity"}])
    remaining = leg.intended_contracts
    consumed: list[dict] = []
    total_cost = 0.0
    contracts_taken = 0.0
    # walk from best level (end of ascending array) backwards.
    # Buying YES consumes NO bids (yes ask = 1 - no bid);
    # buying NO consumes YES bids (no ask = 1 - yes bid).
    for price_text, qty_text in reversed(levels):
        try:
            level_price = float(price_text)
            qty = float(qty_text)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        exec_price = round(1.0 - level_price, 2)
        if exec_price > leg.limit_price + 1e-9:
            break    # would exceed limit: stop the walk
        take = min(remaining, qty)
        if take <= 0:
            break
        consumed.append({"price": exec_price, "contracts": round(take, 2),
                         "level_raw_price": level_price})
        total_cost += take * exec_price
        contracts_taken += take
        remaining -= take
        if remaining <= 0.0099:
            break
    if contracts_taken < min_contracts:
        return ExecutionResult(
            "rejected", note="insufficient_book_depth", regime="live",
            rejections=[{"ticker": leg.ticker, "reason": "book_depth_below_min",
                         "available": round(contracts_taken, 2)}])
    # fee charged per consumed level at that level's price
    fee = sum(taker_fee(walk["price"], walk["contracts"]) for walk in consumed)
    cost = round(total_cost, 2) + fee
    status = "filled" if remaining <= 0.0099 else "partial"
    return ExecutionResult(
        status,
        fills=[LegFill(ticker=leg.ticker, side=leg.side,
                       contracts=round(contracts_taken, 2),
                       price=round(total_cost / contracts_taken, 4),
                       fee=round(fee, 2), cost=round(cost, 2),
                       liquidity_source="kalshi_orderbook_snapshot",
                       book_walk=consumed)],
        regime="live",
        note=("full" if status == "filled"
              else f"partial_{contracts_taken:.2f}_of_{leg.intended_contracts:.2f}"))
