#!/usr/bin/env python3
"""Kalshi fee model — transcribed from the official fee schedule.

SOURCE OF TRUTH
    Kalshi Fee Schedule, "Last updated and effective: July 7, 2026"
    https://kalshi.com/docs/kalshi-fee-schedule.pdf
    (mirrored: https://kalshi.com/fee-schedule)

Official formulas, quoted verbatim from the schedule:

    Trading fees
        fees = round up(M x 0.07 x C x P x (1-P))
        P = the price of a contract in dollars (50 cents is 0.5)
        C = the number of contracts being traded
        M = the multiplier for each contract (default is 1 unless otherwise indicated)
        "Trading fees are only charged for orders that are immediately matched with
         orders sitting on the orderbook."          -> this is the TAKER fee

    Maker fees
        fees = round up(M x 0.0175 x C x P x (1-P))
        "Maker fees are charged for orders placed that are not immediately matched
         and are instead left as resting orders on the orderbook."

    Settlement fees
        "There is no settlement fee."

    Membership fees
        "There is no membership fee."

Per-series multipliers (same schedule, "Non-Standard Fees" table, verbatim):
    KXNFLGAME              "Professional Football Game"                   Maker 1  Taker 1
    KXNFLCOMBOS            "Combos (excluding uncorrelated NFL
                            Championship combos)"                         Maker 2  Taker 1
    KXMLBGAME, KXNBA, KXNCAAF, KXNHL, ...                                  Maker 1  Taker 1

Key consequence for this competition: a fee is charged WHEN A TRADE EXECUTES and
does not depend on whether the contract later wins or loses. The earlier version of
this project charged "7% of profit at settlement", which under-charged losing trades
(nothing) and mis-stated winning trades. Both are corrected here.

Rounding: the schedule rounds UP so that fee + positionCost lands on a centicent
($0.000001). For modelling at cent precision we round up to the nearest cent, which
matches every row of the published "General Trading Fees Table" (e.g. 100 contracts
at $0.45: 0.07 x 100 x 0.45 x 0.55 = 1.7325 -> $1.74, as published).
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_CEILING, InvalidOperation

# Multipliers published in the official schedule
TAKER_RATE = 0.07
MAKER_RATE = 0.0175

# The schedule's rounding targets: the exchange settles fees at 1e-6 ("centicent")
# granularity, and the published per-100-contract table is expressed in cents.
_CENTICENT = Decimal("0.000001")
_CENT = Decimal("0.01")

# Arithmetic is done in Decimal, not float. In binary floating point
# 0.07 * 100 * 0.6 * 0.4 == 1.6800000000000002, which would round UP to $1.69 and
# contradict the published table ($1.68). Decimal makes the published table exact.


# Per-series multipliers ("Non-Standard Fees" table). Default 1 unless listed.
# Only entries relevant to this project are transcribed; anything absent is treated
# as the documented default of 1 (flagged by the caller if it matters).
SERIES_MULTIPLIERS: dict[str, dict[str, float]] = {
    # series_ticker: {"maker": M, "taker": M}
    "KXNFLGAME": {"maker": 1, "taker": 1},
    "KXNFLCOMBO": {"maker": 2, "taker": 1},
}

def _dec(value) -> Decimal:
    """Exact Decimal from a float/int/str without binary-float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def series_multiplier(series_ticker: str | None, maker: bool = False) -> float:
    """Published multiplier for a series; defaults to 1 per the schedule."""
    if not series_ticker:
        return 1.0
    row = SERIES_MULTIPLIERS.get(series_ticker)
    if not row:
        return 1.0
    return float(row["maker" if maker else "taker"])


def kalshi_fee_raw(price: float, contracts: float, maker: bool = False,
                   multiplier: float = 1.0) -> float:
    """Unrounded fee: M x rate x C x P x (1-P).

    Returned as a float for reporting; the underlying computation is exact decimal.
    """
    rate = _dec(MAKER_RATE if maker else TAKER_RATE)
    raw = rate * _dec(multiplier) * _dec(contracts) * _dec(price) * (Decimal(1) - _dec(price))
    return float(raw)


def kalshi_fee_precise(price: float, contracts: float, maker: bool = False,
                       multiplier: float = 1.0) -> float:
    """Fee rounded up to the exchange's centicent (1e-6) granularity."""
    raw = _raw_decimal(price, contracts, maker=maker, multiplier=multiplier)
    if raw <= 0:
        return 0.0
    return float(raw.quantize(_CENTICENT, rounding=ROUND_CEILING))


def _raw_decimal(price, contracts, maker: bool, multiplier) -> Decimal:
    try:
        p = _dec(price)
        c = _dec(contracts)
        m = _dec(multiplier)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)
    if c <= 0:
        return Decimal(0)
    if p < 0:
        p = Decimal(0)
    if p > 1:
        p = Decimal(1)
    rate = _dec(MAKER_RATE if maker else TAKER_RATE)
    return rate * m * c * p * (Decimal(1) - p)


def kalshi_fee(price: float, contracts: float, maker: bool = False,
               multiplier: float | None = None,
               series_ticker: str | None = None) -> float:
    """Fee in dollars, rounded up to the nearest cent.

    Matches the published "General Trading Fees Table", e.g.
        P=$0.50, C=100 -> $1.75
        P=$0.45, C=100 -> $1.74
        P=$0.10, C=100 -> $0.63
        P=$0.01, C=100 -> $0.07
    """
    if contracts is None or float(contracts) <= 0 or price is None:
        return 0.0
    if multiplier is None:
        multiplier = series_multiplier(series_ticker, maker=maker)
    raw = _raw_decimal(price, contracts, maker=maker, multiplier=multiplier)
    if raw <= 0:
        return 0.0
    return float(raw.quantize(_CENT, rounding=ROUND_CEILING))


def entry_fees(legs: list[dict], maker: bool = False) -> float:
    """Total taker fees to open a (possibly multi-leg) position.

    Every leg is an independent order on its own market, so each leg is charged its
    own fee on the number of contracts actually filled. For a synthetic parlay this
    is where the "fees compound per leg" effect the strategy notes describe comes
    from — and it is now priced from the official formula instead of an assumption.
    """
    total = 0.0
    for leg in legs:
        price = leg.get("exec_price")
        if price is None:
            price = leg.get("entry_price")
        qty = leg.get("quantity") or 0
        if price is None or qty <= 0:
            continue
        total += kalshi_fee(price, qty, maker=maker,
                            series_ticker=leg.get("series_ticker"))
    return round(total, 6)
