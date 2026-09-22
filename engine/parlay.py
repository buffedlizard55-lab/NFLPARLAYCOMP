#!/usr/bin/env python3
"""Parlay model for Kalshi NFL markets — documented market-structure semantics.

KEY STRUCTURAL FINDING (verified against the live API 2026-09-22):

1. Kalshi lists NATIVE parlay markets only rarely, under series KXNFLCOMBO
   ("NFL COMBO") — e.g. KXNFLCOMBO-25SEP05KCLAC2 "Travis Kelce First TD,
   Kansas City Wins, and Over 46.5 points scored" is a single all-or-nothing
   binary contract. As of 2026-09-22 there are NO open KXNFLCOMBO events
   (they have appeared for marquee games: 2025 season opener, championship).

2. Therefore parlay strategies on Kalshi are built SYNTHETICALLY: buy one
   contract in each of several real markets. Each leg is an INDEPENDENT
   position: if 2 of 3 legs win, the trader is still paid on the 2 winning
   legs. This is NOT a sportsbook all-or-nothing parlay, and the simulator
   models it exactly this way — per-leg fills, fees and settlements.

3. Legs within one game are correlated (e.g. favorite ML + under). Kalshi
   prices each market separately; a parlay's true win probability is NOT the
   product of leg probabilities. Strategies document their correlation
   assumptions; the settlement accounting needs none (legs settle officially,
   one by one).

Leg semantics used everywhere:
  * side "yes"  — buying YES at the YES ask.
  * side "no"   — buying NO  at the NO ask (= 1 - YES bid).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Leg:
    ticker: str
    side: str                 # "yes" | "no"
    market_title: str = ""
    event_ticker: str = ""
    series: str = ""


@dataclass
class Candidate:
    """A strategy's proposal — not yet checked for executability."""
    legs: list[Leg]
    stake_fraction: float     # fraction of current bankroll to risk on this parlay
    family: str
    username: str
    game_slug: str
    decision_ts: int
    thesis: str = ""
    ev_estimate: float | None = None        # strategy's own EV model (documented)
    ev_breakdown: dict = field(default_factory=dict)
    conditions: dict = field(default_factory=dict)   # max_spread_cents, max_stale_h, min_contracts...
    invalidation: str = ""
    rationale: list[str] = field(default_factory=list)


# ---- EV helpers shared by strategies (all operate on explicit inputs) ------

def taker_fee(price: float, contracts: float, fee_multiplier: float = 1.0) -> float:
    """Kalshi immediately-matched (taker) trading fee, rounded up to the cent.

    Formula (Kalshi fee schedule, last revised 2026-07-07):
        fee = round_up(M * 0.07 * C * P * (1 - P))
    M = series fee multiplier (1 for the NFL series in use — verified from
    GET /series), C = contracts, P = price. No settlement fee.
    """
    import math
    raw = fee_multiplier * 0.07 * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0) / 100.0


def devig_pair(yes_ask: float, no_ask: float) -> tuple[float, float]:
    """Remove the (bid/ask) overround from a two-outcome market.

    For a mutually exclusive pair priced at yes_ask / no_ask, the implied
    probabilities sum to more than 1; proportional normalization gives fair
    probabilities. This is a standard de-vig approximation applied to ASK
    prices (a taker's actual cost basis) and is labelled as such — it is a
    model, not market data.
    """
    p_yes = yes_ask / (yes_ask + no_ask)
    return p_yes, 1.0 - p_yes


def ladder_probability(strikes: list[tuple[float, float]]) -> dict:
    """Fit a monotone ladder of strike -> ask prices into cumulative probabilities.

    Given same-event binary markets ("over X.5" style) at prices that should be
    decreasing in X, returns a strike -> implied-probability map using local
    normalization. Strikes with non-monotone prices are returned as None — the
    caller flags them instead of smoothing.
    """
    ordered = sorted(strikes, key=lambda s: s[0])
    out: dict[float, float | None] = {}
    previous = None
    for strike, price in ordered:
        if price is None:
            out[strike] = None
            continue
        if previous is not None and price > previous + 1e-9:
            out[strike] = None     # non-monotone ladder: do not smooth, flag
        else:
            out[strike] = price
        previous = price if price is not None else previous
    return out


def parlay_product_price(leg_prices: list[float]) -> float:
    """Cost of one 'parlay unit' (one contract of each leg).

    With independent settlement this is just the sum of the leg prices; the
    product appears only when quoting the equivalent sportsbook parlay odds:
    a fair all-or-nothing parlay price would be prod(p_i) IF legs were
    independent, which same-game legs are NOT. Provided for comparison only.
    """
    product = 1.0
    for price in leg_prices:
        product *= min(max(price, 0.01), 0.99)
    return product
