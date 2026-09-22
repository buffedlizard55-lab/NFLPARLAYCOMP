#!/usr/bin/env python3
"""Order-book depth modelling for realistic paper execution.

Why this module exists
----------------------
Two modelling mistakes are easy to make and both were present before:

1. **Double-counting the spread.** Quoting an execution price of the ask already
   means the order crossed the spread. Adding a further "slippage" percentage on top
   charges the trader twice for the same thing.

2. **Ignoring depth.** The ask price is only good for the quantity resting at the
   best level. A 400-contract order against a 50-contract top level does not fill at
   the best ask; it walks up the book.

This module prices an order by consuming real order-book levels when a verified
snapshot exists, and otherwise falls back to top-of-book only — explicitly flagged,
never silently estimated.

Kalshi order-book shape (verified against the official API reference and the
`orderbook_fp` payload returned by GET /markets/{ticker}/orderbook):

    {"orderbook": {"yes": [[price_cents, qty], ...],
                   "no":  [[price_cents, qty], ...]}}
    {"orderbook_fp": {"yes_dollars": [["0.5800", "120.00"], ...],
                      "no_dollars":  [["0.4000", "80.00"], ...]}}

In a binary market the book is quoted as resting *bids* on each side. Buying YES
matches resting NO bids: a NO bid at 0.40 is someone willing to sell YES at 0.60.
So YES asks are `1 - no_bid_price`, in ascending price order.
"""
from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _container(book: dict) -> dict:
    """Unwrap the API envelope.

    GET /markets/{ticker}/orderbook returns the book nested under "orderbook" (or
    "orderbook_fp"); snapshot files in this project wrap that payload one level
    deeper again as {"book": {...}}. Accept any of those shapes.
    """
    if not isinstance(book, dict):
        return {}
    if "book" in book and isinstance(book["book"], dict) and (
            "orderbook" in book["book"] or "orderbook_fp" in book["book"]
            or "yes" in book["book"] or "no" in book["book"]):
        book = book["book"]
    if isinstance(book.get("orderbook_fp"), dict):
        return book["orderbook_fp"]
    if isinstance(book.get("orderbook"), dict):
        return book["orderbook"]
    return book


def _levels(book: dict, side: str) -> list[tuple[float, float]]:
    """Normalised [(price, quantity)] bids for `side` ('yes' or 'no'), best first.

    Accepts both the cent-integer shape (`yes`/`no`) and the fixed-point dollar
    shape (`yes_dollars`/`no_dollars`). Prices are returned in dollars.
    """
    container = _container(book)
    if not container:
        return []
    raw = container.get(f"{side}_dollars") or container.get(side) or []
    out: list[tuple[float, float]] = []
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _to_float(row[0])
        qty = _to_float(row[1])
        if price is None or qty is None or qty <= 0:
            continue
        # The non-`_fp` endpoint quotes cents as integers.
        if price > 1.0:
            price = price / 100.0
        out.append((price, qty))
    # Best bid = highest price.
    out.sort(key=lambda level: level[0], reverse=True)
    return out


def ask_levels(book: dict, side: str) -> list[tuple[float, float]]:
    """Price levels at which we can BUY `side`, best (lowest) first.

    Buying YES takes the other side's bids: YES ask = 1 - (NO bid price).
    Buying NO takes YES bids:           NO ask  = 1 - (YES bid price).

    Note the comparison is case-insensitive: callers pass "yes"/"YES" interchangeably.
    """
    opposite = "no" if (side or "").upper() == "YES" else "yes"
    # Cheapest ask first (best price for a buyer).
    return sorted(
        ((round(1.0 - price, 6), qty) for price, qty in _levels(book, opposite)),
        key=lambda level: level[0])


def walk_book(book: dict, side: str, contracts: float) -> dict:
    """Price `contracts` of `side` against the snapshot book.

    Returns a dict describing the fill:
        filled_contracts, unfilled_contracts, average_price, worst_price,
        cost, slippage_vs_best, levels_consumed, depth_sufficient
    """
    levels = ask_levels(book, side)
    remaining = float(contracts)
    filled = 0.0
    cost = 0.0
    worst = None
    levels_used = 0
    best = levels[0][0] if levels else None

    for price, qty in levels:
        if remaining <= 0:
            break
        take = min(remaining, qty)
        cost += take * price
        filled += take
        remaining -= take
        worst = price
        levels_used += 1

    return {
        "filled_contracts": round(filled, 6),
        "unfilled_contracts": round(max(0.0, remaining), 6),
        "average_price": round(cost / filled, 6) if filled else None,
        "worst_price": worst,
        "best_price": best,
        "cost": round(cost, 6),
        "slippage_vs_best": round((cost / filled - best), 6) if filled and best is not None else None,
        "levels_consumed": levels_used,
        "depth_sufficient": remaining <= 1e-9 and filled > 0,
    }


def book_depth_dollars(book: dict, side: str) -> float | None:
    """Total dollars available to buy `side`, or None when no book is supplied."""
    levels = ask_levels(book, side)
    if not levels:
        return None
    return round(sum(price * qty for price, qty in levels), 6)
