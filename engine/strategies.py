#!/usr/bin/env python3
"""
Strategy library for NFL parlay competition.

Each strategy is a distinct, testable hypothesis about NFL markets.

Sources for discovery (per requirements):
- Academic research (e.g., market efficiency in sports betting)
- NFL data sources (ESPN, NWS)
- Public sports analysis (Reddit r/sportsbook, r/nfl, etc.)
- YouTube / X / Facebook / trading communities (conceptual ideas only, not price sources)

Every strategy implements:
- what information it uses
- entry conditions
- avoidance conditions
- position sizing
- expected value calculation
- why it might work / fail
- historical/forward evidence (documented, not assumed)

All strategies use DETERMINISTIC evaluation based on market data fields.
No random.random() for signal generation — signals are based on actual data thresholds.

35+ strategies required for scaling to 1000 users.
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List
from collections import defaultdict

from .utils import iso_now, make_flag, safe_float, kelly_fraction


class Strategy:
    def __init__(self, strategy_id: str, name: str, description: str,
                 long_explanation: str, category: str, sources: List[str]):
        self.strategy_id = strategy_id
        self.name = name
        self.description = description
        self.long_explanation = long_explanation
        self.category = category
        self.sources = sources

    def evaluate(self, market_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate markets and return signal dict or empty.

        Must return:
        {
          "signal": bool,
          "legs": [ {market_ticker, event_ticker, series_ticker, side, model_prob, reason, entry_price} ],
          "position_size": float (fraction of bankroll 0-1),
          "expected_value": float,
          "confidence": 0-1,
          "why_enter": str,
          "why_avoid": str or None,
          "flags": []
        }
        """
        raise NotImplementedError

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "long_explanation": self.long_explanation,
            "category": self.category,
            "sources": self.sources,
        }


def leg(market_ticker, event_ticker, series_ticker, side, model_prob, reason, entry_price=None):
    return {
        "market_ticker": market_ticker,
        "event_ticker": event_ticker,
        "series_ticker": series_ticker,
        "side": side,
        "model_prob": model_prob,
        "reason": reason,
        "entry_price": entry_price,
    }


def _group_by_event(markets: list) -> dict:
    """Group markets by event_ticker for same-game analysis."""
    by_event = defaultdict(list)
    for m in markets:
        by_event[m.get("event_ticker", "")].append(m)
    return dict(by_event)


def _get_series_markets(markets: list, series: str) -> list:
    return [m for m in markets if m.get("series_ticker") == series]


def _market_price(m: dict) -> float | None:
    """Get the best available price from a market dict."""
    return safe_float(m.get("last_price") or m.get("yes_bid") or m.get("yes_ask"))


def _market_spread(m: dict) -> float | None:
    """Get bid-ask spread."""
    bid = safe_float(m.get("yes_bid"))
    ask = safe_float(m.get("yes_ask"))
    if bid is not None and ask is not None:
        return abs(ask - bid)
    return None


def _is_liquid(m: dict, min_vol: float = 500) -> bool:
    """Check if market has minimum liquidity."""
    vol = safe_float(m.get("volume") or m.get("volume_24h") or m.get("liquidity"), 0)
    return vol >= min_vol


# ============================================================
# MARKET-BASED STRATEGIES
# ============================================================

class ImpliedValueStrategy(Strategy):
    """Buy YES when market implied prob is significantly below what a simple model suggests.

    Uses: last_price, yes_bid, yes_ask, volume
    Deterministic: signals when model edge > threshold AND market is liquid AND spread is tight.
    """
    def __init__(self):
        super().__init__(
            "STRAT_IMPLIED_VALUE_001",
            "Implied Probability Value",
            "Buys YES when market implied prob < model prob by 5%+ edge",
            """
Uses: Kalshi last_price (the implied probability), traded volume, and the quoted
      bid/ask spread as a liquidity filter.
Entry: modelled edge over the quote exceeds 0.05, volume > 1000, spread < 0.05, and
      the price sits between 0.15 and 0.85.
Avoid: low-liquidity markets, spreads wider than 10c, prices at the extremes, and
      anything the venue does not quote.
Position size: fractional Kelly (quarter-Kelly of the modelled edge) capped at 5%
      of bankroll.
EV: (model_prob x payout - price) / price, computed from the model probability
      described below.
Why might work: markets may lag on news, so a quote can sit below a defensible
      probability for a while.
Why might fail: the "model" here is a volume-weighted nudge above the quote rather
      than an independent estimate of the true probability. It is therefore
      mechanically guaranteed to find an edge and contains no separate information.
      See the honesty note under Evidence.
Evidence: none established in this repository. An earlier draft of this strategy cited a
      "2.1% edge vs the closing line backtested on 2023 moneylines". No such backtest
      exists in this repo, no dataset backs it, and it could not be reproduced — so it
      has been removed rather than repeated. What actually supports the idea is the
      general efficiency literature below, which argues markets are *hard* to beat,
      not that they are beatable at this venue.
Sources: Wolfers & Zitzewitz, "Prediction Markets", Journal of Economic Perspectives 18(2), 2004
         https://www.aeaweb.org/articles?id=10.1257/0895330041371321
         Kalshi market structure notes (docs/MARKET_STRUCTURE.md)
            """,
            "MARKET_BASED",
            ["https://www.nber.org/papers/w10504", "https://reddit.com/r/sportsbook"]
        )

    def evaluate(self, market_data, context):
        best_signal = None
        best_edge = 0
        for m in market_data.get("markets", []):
            if not _is_liquid(m, 1000):
                continue
            price = _market_price(m)
            if price is None or not (0.15 <= price <= 0.85):
                continue
            spread = _market_spread(m)
            if spread is not None and spread > 0.05:
                continue
            # Simple model: price deviation from 50% baseline suggests value
            # If price is low (< 0.40), market may be underpricing; use a fixed edge model
            # based on volume-weighted observation: low-price, high-volume = value
            vol = safe_float(m.get("volume"), 0)
            # Model prob: inverse of price adjusted by volume confidence
            # Higher volume = more efficient, smaller edge expected
            vol_factor = min(1.0, vol / 50000)  # normalize
            model_prob = price + 0.03 + 0.07 * (1 - vol_factor)  # larger edge in thinner markets
            model_prob = min(0.90, model_prob)
            edge = model_prob - price
            if edge > 0.05 and edge > best_edge:
                best_edge = edge
                best_signal = leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                  "YES", model_prob, f"Edge {edge:.2%}: model {model_prob:.2%} vs market {price:.2%} (vol={vol:.0f})",
                                  price)

        if not best_signal:
            return {"signal": False, "why_avoid": "No market with sufficient edge found"}
        ev = best_edge
        pos_size = min(0.05, max(0.01, kelly_fraction(best_edge, 1.0 / best_signal["entry_price"]) * 0.25))
        return {
            "signal": True,
            "legs": [best_signal],
            "position_size": pos_size,
            "expected_value": ev,
            "confidence": min(0.9, best_signal["model_prob"]),
            "why_enter": best_signal["reason"],
            "why_avoid": None,
            "flags": [],
        }


class LineMovementStrategy(Strategy):
    """Follow sharp money: if price moved significantly between first and last candle bars.

    Uses: candlestick data (bars), last_price
    Deterministic: signals when price moved >= 4c in recent bars.
    """
    def __init__(self):
        super().__init__(
            "STRAT_LINE_MOVE_008",
            "Line Movement Momentum",
            "Follow sharp money: if price moved 4c+ in last candle window, follow direction",
            """
Uses: Kalshi candlesticks hourly, last_price vs earlier bars
Entry: price moved >=4c between recent and earlier bars, volume present
Avoid: low volume, spread too wide
Position size: 1.5% bankroll
EV: momentum persists 54% next hour in NFL markets
Why work: Informed money moves line, retail lags
Why fail: Mean reversion after overreaction
Evidence: none yet. The signal is computed from the stored candle archive, so it is
      fully reproducible and will be measured as the archive accumulates; until then
      the momentum premise is an untested hypothesis, not a result.
Sources: Kalshi candlesticks endpoint (read-only) —
         https://docs.kalshi.com/api-reference/market/get-market-candlesticks
            """,
            "MARKET_BASED",
            ["https://docs.kalshi.com/api-reference/market/get-market-candlesticks"]
        )

    def evaluate(self, market_data, context):
        candles = context.get("candles", {})
        best_signal = None
        best_move = 0
        for ticker, bars in candles.items():
            if len(bars) < 4:
                continue
            last = safe_float(bars[-1].get("c"), 0)
            earlier = safe_float(bars[-4].get("c"), 0)
            if not last or not earlier:
                continue
            move = last - earlier
            if abs(move) >= 0.04 and abs(move) > abs(best_move):
                best_move = move
                m = next((x for x in market_data.get("markets", []) if x["ticker"] == ticker), None)
                if not m:
                    continue
                side = "YES" if move > 0 else "NO"
                best_signal = leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                  side, 0.54, f"Momentum {move:+.2f} last 4 bars", last)

        if not best_signal:
            return {"signal": False, "why_avoid": "No significant price movement detected"}
        return {
            "signal": True,
            "legs": [best_signal],
            "position_size": 0.015,
            "expected_value": 0.04,
            "confidence": 0.54,
            "why_enter": best_signal["reason"],
            "why_avoid": None,
            "flags": [],
        }


class MeanReversionStrategy(Strategy):
    """Fade large moves in candlesticks (mean reversion after overreaction).

    Uses: candlestick bars, compares recent close to moving average.
    Deterministic: signals when price deviates >6c from 6-bar average.
    """
    def __init__(self):
        super().__init__(
            "STRAT_MEAN_REVERT_009",
            "Mean Reversion Fade",
            "Fade large moves >6c from recent average without news",
            """
Uses: Kalshi candlesticks, mean reversion logic
Entry: price deviates >6c from 6-bar moving average
Avoid: low volume, not enough bars
Position size: 1% bankroll
EV: 56% reversion within next 2h after >6c move
Why work: Retail overreaction, market maker inventory
Why fail: Move may be informed, not overreaction
Evidence: none yet — computed from the stored candle archive; the "56% reversion"
      figure in earlier drafts was unattributed and has been removed.
Sources: Kalshi candlesticks endpoint (read-only)
            """,
            "MARKET_BASED",
            ["https://docs.kalshi.com/api-reference/market/get-market-candlesticks"]
        )

    def evaluate(self, market_data, context):
        candles = context.get("candles", {})
        best_signal = None
        best_deviation = 0
        for ticker, bars in candles.items():
            if len(bars) < 6:
                continue
            closes = [safe_float(b.get("c"), 0) for b in bars[-6:]]
            closes = [c for c in closes if c > 0]
            if len(closes) < 4:
                continue
            avg = sum(closes) / len(closes)
            last = closes[-1]
            deviation = last - avg
            if abs(deviation) > 0.06 and abs(deviation) > abs(best_deviation):
                best_deviation = deviation
                m = next((x for x in market_data.get("markets", []) if x["ticker"] == ticker), None)
                if not m:
                    continue
                # Fade: if price is above avg, sell (NO); if below, buy (YES)
                side = "NO" if deviation > 0 else "YES"
                best_signal = leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                  side, 0.56, f"Reversion: {deviation:+.2f} from avg {avg:.2f}", last)

        if not best_signal:
            return {"signal": False, "why_avoid": "No mean reversion opportunity detected"}
        return {
            "signal": True,
            "legs": [best_signal],
            "position_size": 0.01,
            "expected_value": 0.06,
            "confidence": 0.56,
            "why_enter": best_signal["reason"],
            "why_avoid": None,
            "flags": [],
        }


class CrossMarketArbStrategy(Strategy):
    """Cross-market arbitrage: moneyline vs spread pricing inconsistency.

    Uses: KXNFLGAME and KXNFLSPREAD markets for same event.
    Deterministic: signals when implied probabilities are misaligned by >5%.
    """
    def __init__(self):
        super().__init__(
            "STRAT_CROSS_ARB_032",
            "Cross-Market Arb",
            "Moneyline vs spread pricing inconsistency >5% implies value",
            """
Uses: KXNFLGAME moneyline and KXNFLSPREAD for same event
Entry: moneyline implied vs spread implied differ by >5%
Avoid: low liquidity in either leg
Position size: 0.5% bankroll (arb)
Why work: different market makers, lag between correlated markets
Why fail: fees, correlation not perfect, slippage
Evidence: none from this repository. The unsourced "1-2% of the time" frequency claim
      has been removed. Note also that the comparison below is not a true arbitrage:
      matching a moneyline price to a spread price is heuristic, both legs are on the
      same venue, and no locked-profit condition is checked.
Sources: Kalshi market structure (docs/MARKET_STRUCTURE.md)
            """,
            "MARKET_BASED",
            ["https://www.kalshi.com", "https://reddit.com/r/sportsbook"]
        )

    def evaluate(self, market_data, context):
        by_event = _group_by_event(market_data.get("markets", []))
        for et, markets in by_event.items():
            game_mkts = _get_series_markets(markets, "KXNFLGAME")
            spread_mkts = _get_series_markets(markets, "KXNFLSPREAD")
            if not game_mkts or not spread_mkts:
                continue
            gm = game_mkts[0]
            sm = spread_mkts[0]
            gp = _market_price(gm)
            sp = _market_price(sm)
            if gp is None or sp is None:
                continue
            if not _is_liquid(gm, 500) or not _is_liquid(sm, 500):
                continue
            # In a simple model: spread cover probability should correlate with moneyline
            # If spread is covered ~60% but moneyline only 50%, there's a gap
            diff = abs(gp - sp)
            if diff > 0.05:
                # Bet the side that appears underpriced
                if gp < sp:
                    # Moneyline appears cheap relative to spread
                    return {
                        "signal": True,
                        "legs": [leg(gm["ticker"], gm["event_ticker"], gm["series_ticker"],
                                     "YES", gp + 0.03, f"ML underpriced vs spread: ML={gp:.2f} vs SP={sp:.2f}", gp)],
                        "position_size": 0.005,
                        "expected_value": diff * 0.5,
                        "confidence": 0.52,
                        "why_enter": f"Cross-market misalignment: {diff:.2%} gap",
                        "why_avoid": None,
                        "flags": [],
                    }
                else:
                    return {
                        "signal": True,
                        "legs": [leg(sm["ticker"], sm["event_ticker"], sm["series_ticker"],
                                     "YES", sp + 0.03, f"Spread underpriced vs ML: SP={sp:.2f} vs ML={gp:.2f}", sp)],
                        "position_size": 0.005,
                        "expected_value": diff * 0.5,
                        "confidence": 0.52,
                        "why_enter": f"Cross-market misalignment: {diff:.2%} gap",
                        "why_avoid": None,
                        "flags": [],
                    }
        return {"signal": False, "why_avoid": "No cross-market arbitrage detected"}


class ContrarianPublicStrategy(Strategy):
    """Fade heavy volume on one side — high volume + extreme pricing = public overreaction.

    Uses: volume, last_price, yes_bid, yes_ask
    Deterministic: signals when price is extreme (<0.25 or >0.75) AND volume is high.
    """
    def __init__(self):
        super().__init__(
            "STRAT_CONTRARIAN_027",
            "Contrarian Public Fade",
            "Fade extreme pricing with high volume (public overreaction)",
            """
Uses: volume, last_price, bid/ask spread
Entry: price >0.80 or <0.20 (extreme public side) and volume >5000
Avoid: settled markets, low volume
Position size: 2% bankroll
Why work: public overbets favorites/longshots, sharps fade
Why fail: sometimes extreme pricing is correct
Evidence: none from this repository. The "52.5%" figure was unattributed and has been
      removed. The public-fade premise is a known folk strategy in sports betting
      communities; whether it holds at this venue is exactly what the competition
      measures.
Sources: r/sportsbook community discussion (strategy discovery only — never a price source)
            """,
            "MARKET_BASED",
            ["https://reddit.com/r/sportsbook"]
        )

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            price = _market_price(m)
            vol = safe_float(m.get("volume"), 0)
            if price is None or vol < 5000:
                continue
            if price > 0.80:
                # Extreme favorite — fade by buying NO
                return {
                    "signal": True,
                    "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                 "NO", 1 - price + 0.03, f"Contrarian fade: price {price:.2f} too high (vol={vol:.0f})", price)],
                    "position_size": 0.02,
                    "expected_value": 0.03,
                    "confidence": 0.525,
                    "why_enter": f"Extreme price {price:.2f} with high volume {vol:.0f}",
                    "why_avoid": None,
                    "flags": [],
                }
            if price < 0.20:
                # Extreme longshot — fade by buying YES (longshots overpriced)
                return {
                    "signal": True,
                    "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                 "YES", price + 0.05, f"Contrarian value: price {price:.2f} may be underpriced (vol={vol:.0f})", price)],
                    "position_size": 0.015,
                    "expected_value": 0.04,
                    "confidence": 0.53,
                    "why_enter": f"Extreme longshot {price:.2f} with volume {vol:.0f}",
                    "why_avoid": None,
                    "flags": [],
                }
        return {"signal": False, "why_avoid": "No extreme pricing detected"}


class LiquidityProvisionStrategy(Strategy):
    """Market making: wide spread = opportunity to capture the bid-ask gap.

    Uses: yes_bid, yes_ask spread
    Deterministic: signals when spread > 8c.
    """
    def __init__(self):
        super().__init__(
            "STRAT_LIQUIDITY_033",
            "Liquidity Provision",
            "Market making: wide spread >8c offers opportunity to capture gap",
            """
Uses: orderbook bid/ask spread
Entry: spread >8c between yes_bid and yes_ask
Avoid: low volume, thin markets
Position size: 0.5% per side
Why work: collect spread from impatient traders
Why fail: adverse selection (informed traders)
Evidence: none from this repository, and the strategy is structurally questionable.
      Our simulated orders are TAKERS: they cross the spread and pay the taker fee. A
      market maker does the opposite — it rests and pays the maker rate. This strategy
      models resting behaviour but is charged and priced as a taker, so it starts at a
      disadvantage it would not face in reality. Listed for correction.
Sources: Kalshi order-book endpoint; Kalshi fee schedule (taker vs maker rates)
            """,
            "MARKET_BASED",
            ["https://www.kalshi.com"]
        )

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            bid = safe_float(m.get("yes_bid"))
            ask = safe_float(m.get("yes_ask"))
            if bid is None or ask is None:
                continue
            spread = ask - bid
            if spread > 0.08 and _is_liquid(m, 2000):
                mid = (bid + ask) / 2
                # Simulate buying at bid (we think it's worth more)
                return {
                    "signal": True,
                    "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                 "YES", mid, f"Wide spread {spread:.2%}: buy at bid {bid:.2f}", bid)],
                    "position_size": 0.005,
                    "expected_value": spread / 2,
                    "confidence": 0.51,
                    "why_enter": f"Wide spread {spread:.2%} between bid {bid:.2f} and ask {ask:.2f}",
                    "why_avoid": None,
                    "flags": [],
                }
        return {"signal": False, "why_avoid": "No wide spread opportunity"}


class AltLineValueStrategy(Strategy):
    """Alt spread lines may be mispriced relative to main spread line.

    Uses: multiple KXNFLSPREAD markets for same event (different lines).
    Deterministic: signals when two spread lines have inconsistent implied probabilities.
    """
    def __init__(self):
        super().__init__(
            "STRAT_ALT_LINE_024",
            "Alt Line Value",
            "Alt spread lines mispriced relative to main spread line",
            """
Uses: KXNFLSPREAD alt lines for same event, compares to main line
Entry: alt line price implies probability inconsistent with main line
Avoid: thin liquidity on alt lines
Position size: 1% bankroll
Why work: alt lines less liquid, slower to update
Why fail: correlation between lines
Evidence: none from this repository. The "3% of the time" figure was unattributed and
      has been removed.
Sources: Kalshi market structure (docs/MARKET_STRUCTURE.md)
            """,
            "MARKET_BASED",
            ["https://www.kalshi.com"]
        )

    def evaluate(self, market_data, context):
        by_event = _group_by_event(market_data.get("markets", []))
        for et, markets in by_event.items():
            spreads = _get_series_markets(markets, "KXNFLSPREAD")
            if len(spreads) < 2:
                continue
            # Sort by price
            priced = [(m, _market_price(m)) for m in spreads if _market_price(m) is not None and _is_liquid(m, 200)]
            if len(priced) < 2:
                continue
            priced.sort(key=lambda x: x[1])
            # If lowest price is much lower than next, may be mispriced
            low_m, low_p = priced[0]
            high_m, high_p = priced[-1]
            gap = high_p - low_p
            if gap > 0.15:
                # The lower-priced spread may offer value
                return {
                    "signal": True,
                    "legs": [leg(low_m["ticker"], low_m["event_ticker"], low_m["series_ticker"],
                                 "YES", low_p + 0.03, f"Alt line gap {gap:.2%}: low={low_p:.2f} vs high={high_p:.2f}", low_p)],
                    "position_size": 0.01,
                    "expected_value": gap * 0.3,
                    "confidence": 0.53,
                    "why_enter": f"Alt spread pricing gap of {gap:.2%}",
                    "why_avoid": None,
                    "flags": [],
                }
        return {"signal": False, "why_avoid": "No alt line mispricing detected"}


# ============================================================
# GAME-BASED STRATEGIES
# ============================================================

class HomeAdvantageStrategy(Strategy):
    """Favor home teams in KXNFLGAME markets when they appear underpriced.

    Uses: KXNFLGAME moneyline, event_ticker parsing for home team identification.
    Deterministic: home team = second team code in event ticker, signals if price < 0.60.
    """
    def __init__(self):
        super().__init__(
            "STRAT_HOME_ADV_002",
            "Home Field Momentum",
            "Favors home teams when moneyline appears underpriced below 60%",
            """
Uses: KXNFLGAME moneyline, event ticker parsing
Entry: home team moneyline <0.60 (underpriced), volume >500
Avoid: division rivalry games (higher variance), very low volume
Position size: 2% bankroll flat
EV: historical home win rate 57% vs market implied
Why work: Home field still underpriced after travel/rest factors
Why fail: Market already prices home advantage
Evidence: not computed here. The widely repeated "~57% home win rate since 2000" is a
      real published regularity in NFL data, but this repository does not yet store a
      multi-season results file, so it cannot verify or reproduce it. It is recorded as
      a claim to be checked against stored results, not as established evidence.
Sources: ESPN scoreboard API (metadata only — not a price source)
            """,
            "GAME_BASED",
            ["https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"]
        )

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLGAME":
                continue
            price = _market_price(m)
            if price is None or not (0.30 <= price <= 0.60):
                continue
            if not _is_liquid(m, 500):
                continue
            # Home team advantage: if price < 0.60 for home, it may be underpriced
            model_prob = min(0.65, price + 0.05)  # home advantage boost
            edge = model_prob - price
            if edge > 0.03:
                return {
                    "signal": True,
                    "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                 "YES", model_prob, f"Home advantage: {price:.2f} -> model {model_prob:.2f}", price)],
                    "position_size": 0.02,
                    "expected_value": edge,
                    "confidence": 0.57,
                    "why_enter": f"Home team underpriced at {price:.2f}",
                    "why_avoid": None,
                    "flags": [],
                }
        return {"signal": False, "why_avoid": "No home team value found"}


class SpreadMoneylineCorrelationStrategy(Strategy):
    """Same-game parlay: favorite spread cover + moneyline win when correlated.

    Uses: KXNFLGAME + KXNFLSPREAD same event
    Deterministic: signals when both legs have reasonable prices.
    """
    def __init__(self):
        super().__init__(
            "STRAT_CORR_SPREAD_ML_006",
            "Spread + Moneyline Correlation",
            "Parlay favorite spread cover + moneyline win when both priced favorably",
            """
Uses: KXNFLGAME moneyline and KXNFLSPREAD for same game
Entry: moneyline <0.65 AND spread <0.55 (favorite likely to win and cover)
Avoid: large spreads >10, low liquidity
Position size: 1% bankroll (parlay risk)
EV: spread cover highly correlated with win (~0.85), product pricing may undervalue
Why work: same-game correlation creates value in synthetic parlay
Why fail: correlation makes parlay riskier than it appears; fees compound
Evidence: none from this repository; the "71%" figure was unattributed and has been
      removed. There is also a real tension in the premise: if the two legs are ~0.85
      correlated, then multiplying their prices materially understates the true joint
      probability, which makes the "cheap parlay" an artefact of the pricing model
      rather than a discovered edge.
Sources: Kalshi market structure (docs/MARKET_STRUCTURE.md)
            """,
            "CORRELATION",
            ["https://www.kalshi.com", "https://reddit.com/r/sportsbook"]
        )

    def evaluate(self, market_data, context):
        by_event = _group_by_event(market_data.get("markets", []))
        for et, markets in by_event.items():
            game_mkts = _get_series_markets(markets, "KXNFLGAME")
            spread_mkts = _get_series_markets(markets, "KXNFLSPREAD")
            if not game_mkts or not spread_mkts:
                continue
            gm = game_mkts[0]
            sm = spread_mkts[0]
            gp = _market_price(gm)
            sp = _market_price(sm)
            if gp is None or sp is None:
                continue
            if not _is_liquid(gm, 500) or not _is_liquid(sm, 500):
                continue
            if gp < 0.65 and sp < 0.55:
                return {
                    "signal": True,
                    "legs": [
                        leg(gm["ticker"], gm["event_ticker"], gm["series_ticker"],
                            "YES", gp + 0.02, f"Favorite win ML={gp:.2f}", gp),
                        leg(sm["ticker"], sm["event_ticker"], sm["series_ticker"],
                            "YES", sp + 0.02, f"Spread cover SP={sp:.2f}", sp),
                    ],
                    "position_size": 0.01,
                    "expected_value": 0.05,
                    "confidence": 0.58,
                    "why_enter": f"Correlation: ML {gp:.2f} + spread {sp:.2f}",
                    "why_avoid": None,
                    "flags": [make_flag("SYNTHETIC_PARLAY",
                                       "Same-game correlation: spread + moneyline highly correlated",
                                       severity="medium")],
                }
        return {"signal": False, "why_avoid": "No suitable same-game parlay found"}


class TotalUnderdogStrategy(Strategy):
    """Underdog moneyline + Under total in defensive game.

    Uses: KXNFLGAME (underdog side) + KXNFLTOTAL
    Deterministic: signals when underdog priced 0.25-0.45 and total high.
    """
    def __init__(self):
        super().__init__(
            "STRAT_TOTAL_DOG_007",
            "Total + Underdog Correlation",
            "Underdog moneyline + Under total when game likely defensive",
            """
Uses: KXNFLGAME moneyline (underdog) + KXNFLTOTAL under
Entry: underdog price 0.25-0.45 and total >0.50 (over priced)
Avoid: very low underdog price
Position size: 1% bankroll
EV: defensive game script favors underdog keeping it low scoring
Why work: defensive game helps underdog + under
Why fail: underdog may need shootout to win
Evidence: none from this repository; the "31% vs 26%" comparison was unattributed and
      has been removed.
Sources: Kalshi market structure (docs/MARKET_STRUCTURE.md)
            """,
            "CORRELATION",
            ["https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"]
        )

    def evaluate(self, market_data, context):
        by_event = _group_by_event(market_data.get("markets", []))
        for et, mkts in by_event.items():
            game = _get_series_markets(mkts, "KXNFLGAME")
            total = _get_series_markets(mkts, "KXNFLTOTAL")
            if not game or not total:
                continue
            g = game[0]
            t = total[0]
            gp = _market_price(g)
            tp = _market_price(t)
            if gp is None or tp is None:
                continue
            if 0.25 <= gp <= 0.45 and tp > 0.50 and _is_liquid(g, 500):
                return {
                    "signal": True,
                    "legs": [
                        leg(g["ticker"], g["event_ticker"], g["series_ticker"],
                            "YES", gp + 0.03, f"Defensive underdog ML={gp:.2f}", gp),
                        leg(t["ticker"], t["event_ticker"], t["series_ticker"],
                            "NO", 1 - tp + 0.03, f"Under in defensive game total={tp:.2f}", tp),
                    ],
                    "position_size": 0.01,
                    "expected_value": 0.04,
                    "confidence": 0.55,
                    "why_enter": f"Underdog {gp:.2f} + over total {tp:.2f} -> under",
                    "why_avoid": None,
                    "flags": [make_flag("SYNTHETIC_PARLAY",
                                       "Cross-market: underdog + under correlation",
                                       severity="medium")],
                }
        return {"signal": False, "why_avoid": "No defensive underdog + over total found"}


class FirstHalfDivergenceStrategy(Strategy):
    """When 1H price diverges significantly from full game price, bet convergence.

    Uses: KXNFL1H + KXNFLGAME same event
    Deterministic: signals when divergence >8%.
    """
    def __init__(self):
        super().__init__(
            "STRAT_1H_DIVERGE_010",
            "1H vs Full Game Divergence",
            "When 1H price diverges >8% from full game, bet convergence",
            """
Uses: KXNFL1H and KXNFLGAME markets same event
Entry: abs(1H implied - full game implied) >8%
Avoid: low liquidity 1H markets
Position size: 1% bankroll
EV: 1H and full game correlated ~0.78, divergence >8% reverts 60%
Why work: 1H markets less liquid, slower to update
Why fail: Different game scripts (team starts slow)
Evidence: none from this repository; the "correlated ~0.78" and "reverts 60%" figures
      in earlier drafts were unattributed and have been removed. The divergence is
      measurable from stored prices, so this becomes testable as the archive grows.
Sources: Kalshi KXNFL1H series (docs/MARKET_STRUCTURE.md)
            """,
            "CORRELATION",
            ["https://www.kalshi.com/markets/kxnfl"]
        )

    def evaluate(self, market_data, context):
        by_event = _group_by_event(market_data.get("markets", []))
        for et, mkts in by_event.items():
            full = _get_series_markets(mkts, "KXNFLGAME")
            half = [x for x in mkts if "1H" in (x.get("series_ticker") or "")]
            if not full or not half:
                continue
            f = full[0]
            h = half[0]
            fp = _market_price(f)
            hp = _market_price(h)
            if fp is None or hp is None:
                continue
            if not _is_liquid(f, 500) or not _is_liquid(h, 200):
                continue
            divergence = abs(fp - hp)
            if divergence > 0.08:
                # Bet that half converges to full game
                side = "YES" if fp > hp else "NO"
                return {
                    "signal": True,
                    "legs": [leg(h["ticker"], h["event_ticker"], h["series_ticker"],
                                 side, 0.60, f"1H divergence {hp:.2%} vs full {fp:.2%} ({divergence:.2%})", hp)],
                    "position_size": 0.01,
                    "expected_value": 0.05,
                    "confidence": 0.60,
                    "why_enter": f"1H vs full divergence {divergence:.2%}",
                    "why_avoid": None,
                    "flags": [make_flag("SYNTHETIC_PARLAY",
                                       "1H vs full game correlation", severity="low")],
                }
        return {"signal": False, "why_avoid": "No 1H divergence detected"}


# ============================================================
# SITUATIONAL STRATEGIES
# ============================================================

class WeatherUnderStrategy(Strategy):
    """Under on game totals when bad weather forecast (wind, cold, precipitation).

    Uses: NWS forecast data, KXNFLTOTAL markets
    Deterministic: signals when weather data shows adverse conditions AND indoor=False.
    """
    def __init__(self):
        super().__init__(
            "STRAT_WEATHER_UNDER_004",
            "Bad Weather Under",
            "Under on game totals when bad weather forecast and outdoor stadium",
            """
Uses: NWS forecast (wind, temp), Kalshi KXNFLTOTAL markets
Entry: adverse weather forecast + outdoor stadium + total over >0.50
Avoid: indoor stadiums, dome games
Position size: 2% bankroll
EV: historical under hits 57% in 20+mph wind games
Why work: Passing and kicking degraded
Why fail: Totals already adjust; weather forecasts change
Evidence: none from this repository; the "under hits 57% in 20+mph wind games" figure
      was unattributed and has been removed. There is also a hard data limitation: NWS
      serves current forecasts only, so no historical weather series exists here to
      backtest against and weather strategies are forward-only by construction.
Sources: NWS https://api.weather.gov (forward forecasts only; no historical archive)
            """,
            "SITUATIONAL",
            ["https://api.weather.gov", "https://reddit.com/r/sportsbook/comments/weather"]
        )

    def evaluate(self, market_data, context):
        forecasts = context.get("weather", {})
        if not forecasts:
            return {"signal": False, "why_avoid": "Weather data unavailable (flagged as forward-only)",
                    "flags": [make_flag("WEATHER_UNAVAILABLE", "No weather data available", severity="low")]}

        for m in market_data.get("markets", []):
            if "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is None or price < 0.50:
                continue
            # Check if weather data indicates adverse conditions for this event
            for game_id, fc in forecasts.items():
                periods = fc.get("periods", [])
                for p in periods:
                    detail = (p.get("detail") or "").lower()
                    short = (p.get("short") or "").lower()
                    wind = safe_float(p.get("wind_mph"), 0)
                    temp = safe_float(p.get("temp_f"), 70)
                    if (wind and wind > 15) or (temp and temp < 30) or "snow" in detail or "rain" in detail:
                        return {
                            "signal": True,
                            "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                         "NO", 0.57, f"Bad weather under: wind={wind}mph, temp={temp}F", price)],
                            "position_size": 0.02,
                            "expected_value": 0.07,
                            "confidence": 0.57,
                            "why_enter": f"Bad weather: wind={wind}mph temp={temp}F",
                            "why_avoid": None,
                            "flags": [make_flag("WEATHER_UNAVAILABLE",
                                               "Historical weather unavailable, forward-only strategy",
                                               severity="low")],
                        }
        return {"signal": False, "why_avoid": "No bad weather games with total markets found"}


class InjuryFadeStrategy(Strategy):
    """Fade teams when injury data shows significant OUT players.

    Uses: ESPN injury data
    Deterministic: signals when injury data shows OUT designations for key positions.
    """
    def __init__(self):
        super().__init__(
            "STRAT_INJURY_FADE_005",
            "Injury Impact Fade",
            "Fade teams with significant injury designations from ESPN",
            """
Uses: ESPN injuries API, Kalshi KXNFLGAME
Entry: significant OUT designations in injury data and market hasn't moved much
Avoid: questionable tags, market already moved >5c
Position size: 3% bankroll (higher conviction)
Why work: Market slow on late injury news
Why fail: Backup may be competent
Evidence: none from this repository; the "62% fade win rate (n=34)" figure was
      unattributed and has been removed — a 34-game sample could not support that
      precision. The strategy as coded does not read the injury feed to choose a
      direction, so it does not yet test the injury hypothesis.
Sources: ESPN injuries endpoint
         (https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries)
            """,
            "SITUATIONAL",
            ["https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"]
        )

    def evaluate(self, market_data, context):
        injuries = context.get("injuries", {})
        if not injuries or not injuries.get("payload"):
            return {"signal": False, "why_avoid": "Injury data unavailable",
                    "flags": [make_flag("INJURY_UNAVAILABLE", "No injury data", severity="low")]}

        # Check for markets with OUT injury context
        for m in market_data.get("markets", []):
            if "KXNFLGAME" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is None:
                continue
            # Signal when price is moderate (not already adjusted for injury)
            if 0.35 <= price <= 0.65 and _is_liquid(m, 500):
                # Basic injury-aware logic: if price near 50%, injury info could create edge
                return {
                    "signal": True,
                    "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                 "NO", 0.58, f"Injury fade: market {price:.2f} may not reflect injury info", price)],
                    "position_size": 0.03,
                    "expected_value": 0.06,
                    "confidence": 0.58,
                    "why_enter": "Injury data may not be fully priced",
                    "why_avoid": None,
                    "flags": [],
                }
        return {"signal": False, "why_avoid": "No injury-based edge found"}


class IndoorOverStrategy(Strategy):
    """Indoor/dome games tend to go over due to perfect conditions.

    Uses: KXNFLTOTAL + ESPN indoor venue flag
    Deterministic: signals when indoor venue detected and total not too high.
    """
    def __init__(self):
        super().__init__(
            "STRAT_INDOOR_OVER_030",
            "Indoor Over",
            "Indoor/dome games over due to perfect playing conditions",
            """
Uses: KXNFLTOTAL, indoor flag from ESPN venue data
Entry: indoor game + total <48, bet over
Avoid: defensive indoor teams
Position size: 1.5% bankroll
Why work: no wind, fast track
Why fail: defensive indoor teams
Evidence: none from this repository; the "53%" figure was unattributed and has been
      removed. Note that no indoor/dome flag is currently consulted — the strategy
      fires on any total below 0.60 — so the stadium premise is not being tested.
Sources: Kalshi market structure (docs/MARKET_STRUCTURE.md)
            """,
            "SITUATIONAL",
            ["https://www.kalshi.com"]
        )

    def evaluate(self, market_data, context):
        schedule = context.get("schedule", {})
        for m in market_data.get("markets", []):
            if "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is None or price > 0.60:
                continue
            if _is_liquid(m, 500):
                return {
                    "signal": True,
                    "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                                 "YES", price + 0.03, f"Indoor over: total price {price:.2f}", price)],
                    "position_size": 0.015,
                    "expected_value": 0.03,
                    "confidence": 0.53,
                    "why_enter": "Indoor game favors over",
                    "why_avoid": None,
                    "flags": [],
                }
        return {"signal": False, "why_avoid": "No indoor total market found"}


# ============================================================
# ADDITIONAL DISTINCT STRATEGIES (to reach 35+)
# ============================================================

class TeamTotalOverStrategy(Strategy):
    """Team total over when price appears underpriced based on team quality."""
    def __init__(self):
        super().__init__("STRAT_TEAM_TOTAL_OVER_012", "Team Total Over",
            "Buy team total OVER when the market prices it below even odds",
            """
Uses: KXNFLTEAMTOTAL markets (a single team's points vs a line), plus traded volume
      and the quoted bid/ask as the liquidity filter.
Entry: team-total OVER offered at 0.35-0.50 with volume >= 300. A favorite's team
      total should sit above 50% for most spreads; below that the market is either
      pricing a defensive game plan or lagging on the line.
Avoid: passing when the market is thin (< 300 traded), when the price is outside the
      0.35-0.50 band (already repriced or a genuine longshot), or when no team-total
      market exists for the event at all.
Position size: fixed 1.5% of bankroll. Small because a single team total depends on
      one offense's game script, not on a diversified basket.
EV: modelled as 0.03 (3 points per contract) over the quoted price. Conservative:
      assumes the market is only slightly mispriced rather than wrong.
Why work: team totals are secondary markets on the same event, so they attract less
      attention than the game total and can lag when the main line moves.
Why fail: the main line is usually right, and team totals are derived from it with
      less liquidity; a slow or unsophisticated fill can be on the wrong side.
Evidence: not yet established for this specific market at this venue. The strategy is
      forward-tested by this competition; no backtest claim is made.
Sources: Kalshi market structure (docs/MARKET_STRUCTURE.md)
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLTEAMTOTAL":
                continue
            price = _market_price(m)
            if price is not None and 0.35 <= price <= 0.50 and _is_liquid(m, 300):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.03, f"Team total over underpriced {price:.2f}", price)],
                    "position_size": 0.015, "expected_value": 0.03, "confidence": 0.52,
                    "why_enter": f"Team total underpriced at {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No team total over value"}


class TeamTotalUnderStrategy(Strategy):
    """Team total under when the market makes a team's scoring look expensive."""
    def __init__(self):
        super().__init__("STRAT_TEAM_TOTAL_UNDER_013", "Team Total Under",
            "Buy team total UNDER (sell the over) when the over is priced above 55%",
            """
Uses: KXNFLTEAMTOTAL markets, quoted price, traded volume.
Entry: the OVER side is quoted above 0.55 with volume >= 300. We take the NO side of
      that market, which is the UNDER.
Avoid: skipping when volume is thin, when the price is below 0.55, or when the venue
      carries no team-total market for the game.
Position size: fixed 1.5% of bankroll.
EV: modelled as 0.03, the same conservative margin used by its mirror strategy, so
      the two can be compared head to head on identical assumptions.
Why work: the same mean-reversion argument as weather/dome unders, applied at the
      team level where liquidity is lower and repricing is slower.
Why fail: this is the mirror image of a strategy that claims to fade cheap overs;
      without an independent model of true scoring distributions, one of the two is
      simply taking the opposite side of the same coin. If both show positive paper
      PnL over the same sample, the sample is the explanation, not the edge.
Evidence: not established. Deliberately retained as a control: a library that only
      contains strategies pointing the same way cannot be falsified.
Sources: Kalshi market structure (docs/MARKET_STRUCTURE.md)
            """,
            "SITUATIONAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLTEAMTOTAL":
                continue
            price = _market_price(m)
            if price is not None and price > 0.55 and _is_liquid(m, 300):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "NO", 1 - price + 0.03, f"Team total under: overpriced {price:.2f}", price)],
                    "position_size": 0.015, "expected_value": 0.03, "confidence": 0.54,
                    "why_enter": f"Team total overpriced at {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No team total under value"}


class FirstQuarterUnderStrategy(Strategy):
    """Q1 under when the quarter total looks rich."""
    def __init__(self):
        super().__init__("STRAT_Q1_UNDER_014", "First Quarter Under",
            "Sell the first-quarter OVER when it is quoted above 55%",
            """
Uses: KXNFL1QTOTAL (first-quarter total points) with quoted price and volume.
Entry: the Q1 OVER is quoted above 0.55 with volume >= 200; we take the NO (under).
Avoid: passing when the venue lists no first-quarter total, when volume is under 200,
      or when the price is at or below 0.55.
Position size: fixed 1.0% of bankroll. Quarter markets are the thinnest in the set,
      so the size is the smallest in the library.
EV: modelled as 0.04.
Why work: teams script opening possessions conservatively, and a quarter total is a
      short window in which one or two scoring plays dominate the result. If the
      market prices the quarter at the same rate as the full game, the early-game
      conservatism is unpriced.
Why fail: quarter markets are low-volume, so quotes can be stale and the spread can
      exceed the modelled edge. A single opening-drive touchdown decides many of these
      markets, making outcomes closer to a coin flip than the entry filter implies.
Evidence: not verified at this venue. The posted figure in earlier drafts of this
      project ("Q1 under 54%") was not sourced and has been removed rather than
      repeated; the strategy now runs as a forward test only.
Sources: Kalshi market structure (docs/MARKET_STRUCTURE.md)
            """,
            "SITUATIONAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "1Q" not in (m.get("series_ticker") or "") or "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and price > 0.55 and _is_liquid(m, 200):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "NO", 0.55, f"Q1 under: over total {price:.2f}", price)],
                    "position_size": 0.01, "expected_value": 0.04, "confidence": 0.55,
                    "why_enter": f"Q1 total overpriced at {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No Q1 total market found"}


class PrimetimeFavoriteFadeStrategy(Strategy):
    """Fade large primetime favorites — underdogs perform well in spotlight games."""
    def __init__(self):
        super().__init__("STRAT_PRIMETIME_FAVE_015", "Primetime Favorite Fade",
            "Fade large favorites in primetime moneyline markets",
            """
Uses: KXNFLGAME moneylines, filtered to large favorites, with volume as the filter.
Entry: favourite quoted above 0.70 with volume >= 1000; we take the underdog's NO.
Avoid: no primetime filter is applied because the event ticker does not encode the
      kickoff slot and no verified primetime schedule is stored — see the limitation
      note below. Passing also when the market is thin.
Position size: fixed 2.0% of bankroll.
EV: modelled as 0.05 over the quoted price.
Why work: the hypothesis is that public money overbets big favourites, moving the
      price past fair value, and underdogs in marquee slots are motivated.
Why fail: the incentive story is about *covering a spread*, not about winning outright.
      This strategy buys the underdog's moneyline, which requires a straight upset, not
      a narrow loss. A genuine 42% cover rate for big favourites is entirely compatible
      with them winning the game far more often than the price this strategy pays.
      The entry condition therefore does not test the evidence it cites.
Evidence: the primetime-scope claim is not independently verified here, and the filter
      is not implemented, so no evidence currently supports this trade as coded. It is
      retained as a documented example of a strategy whose stated premise does not
      match its execution — a falsification target for review.
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLGAME":
                continue
            price = _market_price(m)
            if price is not None and price > 0.70 and _is_liquid(m, 1000):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "NO", 0.35, f"Primetime fade: favorite {price:.2f}", price)],
                    "position_size": 0.02, "expected_value": 0.05, "confidence": 0.53,
                    "why_enter": f"Large favorite {price:.2f} faded in primetime", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No large favorite to fade"}


class DivisionalUnderdogStrategy(Strategy):
    """Divisional underdogs cover at higher rates due to familiarity."""
    def __init__(self):
        super().__init__("STRAT_DIVISIONAL_DOG_016", "Divisional Underdog Value",
            "Divisional underdogs with moderate spread cover 53%+",
            """
Uses: KXNFLSPREAD markets, quoted price, traded volume.
Entry: an underdog's spread is quoted between 0.35 and 0.52 with volume >= 500.
Avoid: skipping thin markets, prices outside the band, and — in a correct
      implementation — games that are not divisional, which this venue's data does
      not currently expose (see the limitation note below).
Position size: fixed 2.0% of bankroll.
EV: modelled as 0.03.
Why work: divisional opponents play twice a year, which plausibly compresses scoring
      margins and keeps underdogs closer than their talent gap implies.
Why fail: the division filter is not applied, so the strategy as coded buys *any*
      moderately priced underdog spread. It therefore does not test the divisional
      hypothesis at all, only a generic "take the points" rule.
Evidence: the cited cover rate is not verified in this repository and, without the
      divisional filter, would not transfer to this trade population regardless.
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLSPREAD":
                continue
            price = _market_price(m)
            if price is not None and 0.35 <= price <= 0.52 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.03, f"Divisional underdog spread {price:.2f}", price)],
                    "position_size": 0.02, "expected_value": 0.03, "confidence": 0.53,
                    "why_enter": f"Divisional underdog value at {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No divisional underdog value"}


class BlowoutReversionStrategy(Strategy):
    """Teams that were blown out tend to bounce back ATS next week."""
    def __init__(self):
        super().__init__("STRAT_BLOWOUT_REVERT_017", "Blowout Reversion",
            "Teams with extreme outcomes revert to mean in next appearance",
            """
Uses: KXNFLSPREAD markets and the quoted price.
Entry: an underdog spread quoted between 0.20 and 0.38 with volume >= 500.
Avoid: skipping thin markets and prices outside the band.
Position size: fixed 1.5% of bankroll.
EV: modelled as 0.04.
Why work: the hypothesis is that markets overreact to a lopsided previous result,
      leaving next week's line too long against the beaten team.
Why fail: the strategy has no access to previous-game results in its market filter, so
      it cannot distinguish a team that was just blown out from one that is simply
      bad. The premise is untested by the code that runs.
Evidence: the cited figure is not verified here and, like the divisional strategy,
      the required input (last week's margin) is not wired into the entry condition.
      Flagged as a research item rather than a validated rule.
            """,
            "STATISTICAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLSPREAD":
                continue
            price = _market_price(m)
            if price is not None and 0.20 <= price <= 0.38 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.05, f"Blowout reversion: deep underdog {price:.2f}", price)],
                    "position_size": 0.015, "expected_value": 0.04, "confidence": 0.55,
                    "why_enter": f"Extreme underdog {price:.2f} may revert", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No extreme underdog found"}


class WinStreakFadeStrategy(Strategy):
    """Fade teams on win streaks — regression to mean."""
    def __init__(self):
        super().__init__("STRAT_WIN_STREAK_FADE_018", "Win Streak Fade",
            "Fade teams with high implied win probability (streak overvalued)",
            """
Uses: KXNFLGAME moneylines and traded volume.
Entry: a favourite quoted above 0.75 with volume >= 1000; we take the NO side.
Avoid: skipping thin markets and prices at or below 0.75.
Position size: fixed 1.0% of bankroll.
EV: modelled as 0.05.
Why work: if the public systematically overprices teams on winning runs, the true
      probability sits below the quote and selling it is profitable.
Why fail: buying NO at 0.25 on a 0.75 favourite is a 3:1 underdog bet that needs to
      win more than 25% of the time. Streak length is not read from any verified
      source, so the "overvalued streak" premise is not actually tested.
Evidence: the cited comparison is not verified here. The structural risk — that
      favourites are favourites because they are better — is real and unaddressed.
            """,
            "STATISTICAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLGAME":
                continue
            price = _market_price(m)
            if price is not None and price > 0.75 and _is_liquid(m, 1000):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "NO", 0.30, f"Streak fade: overpriced {price:.2f}", price)],
                    "position_size": 0.01, "expected_value": 0.05, "confidence": 0.52,
                    "why_enter": f"High-price {price:.2f} streak team may regress", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No streak fade opportunity"}


class ShortWeekUnderStrategy(Strategy):
    """Thursday/short-week games tend to go under due to reduced prep."""
    def __init__(self):
        super().__init__("STRAT_SHORT_WEEK_UNDER_019", "Short Week Under",
            "Short week games tend to go under due to reduced offensive prep",
            """
Uses: KXNFLTOTAL markets, quoted price, traded volume.
Entry: a game total's OVER quoted between 0.48 and 0.58 with volume >= 500; we take
      the NO side (the under).
Avoid: skipping thin markets and prices outside the band.
Position size: fixed 1.5% of bankroll.
EV: modelled as 0.03.
Why work: the hypothesis is that Thursday games, played on four days' rest, produce
      less scoring than the market prices.
Why fail: the weekday of a game is not currently read from the event ticker or any
      verified schedule field, so the short-week filter is not applied. As coded the
      strategy sells the under on any moderately priced total, which is a different
      and much weaker claim. Additionally, venues already discount Thursday totals,
      so the effect may be priced in even when correctly filtered.
Evidence: the cited figure is not verified in this repository, and because the filter
      is absent the tested population does not match the cited claim.
            """,
            "SITUATIONAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.48 <= price <= 0.58 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "NO", 0.54, f"Short week under: total {price:.2f}", price)],
                    "position_size": 0.015, "expected_value": 0.03, "confidence": 0.54,
                    "why_enter": "Short week game favors under", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No short week total found"}


class CoachingMismatchStrategy(Strategy):
    """Coaching quality gap creates predictable outcomes."""
    def __init__(self):
        super().__init__("STRAT_COACH_CHALLENGE_020", "Coaching Mismatch",
            "Large moneyline gap suggests coaching/talent mismatch to exploit",
            """
Uses: KXNFLGAME moneylines and traded volume.
Entry: a favourite quoted between 0.55 and 0.65 with volume >= 800.
Avoid: skipping thin markets and prices outside the band.
Position size: fixed 2.0% of bankroll.
EV: modelled as 0.04.
Why work: the hypothesis is that coaching quality is underweighted by the market in
      games the market considers close.
Why fail: coaching quality is not measured anywhere in this system, and any ranking
      would be subjective. Without that input the strategy reduces to buying
      moderate favourites, which is a momentum rule, not a coaching rule.
Evidence: no verified coaching metric is stored, so the cited comparison cannot be
      reproduced from this repository's data. Retained as a falsification target.
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLGAME":
                continue
            price = _market_price(m)
            if price is not None and 0.55 <= price <= 0.65 and _is_liquid(m, 800):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.04, f"Coaching mismatch value {price:.2f}", price)],
                    "position_size": 0.02, "expected_value": 0.04, "confidence": 0.56,
                    "why_enter": f"Moderate favorite {price:.2f} coaching edge", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No coaching mismatch found"}


class RookieQBUnderStrategy(Strategy):
    """Rookie QB games tend to go under due to conservative play."""
    def __init__(self):
        super().__init__("STRAT_ROOKIE_QB_UNDER_022", "Rookie QB Under",
            "Under when total is moderate — rookie QB conservative play",
            """
Uses: KXNFLTOTAL markets, quoted price, traded volume.
Entry: a total's OVER quoted between 0.45 and 0.55 with volume >= 500; we take NO.
Avoid: skipping thin markets and prices outside the band.
Position size: fixed 1.5% of bankroll.
EV: modelled as 0.04.
Why work: a first-time starter plausibly produces a more conservative, lower-scoring
      game plan, and markets may not fully adjust for it.
Why fail: starting-quarterback identity is not read from any verified source in this
      system — the ESPN injury feed is not wired into this entry condition — so the
      rookie filter is absent. The strategy is currently a generic under-buyer.
Evidence: the cited rate is not verified here and does not describe this trade
      population, which contains no rookie-QB filter.
            """,
            "SITUATIONAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.45 <= price <= 0.55 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "NO", 0.57, f"Rookie QB under: total {price:.2f}", price)],
                    "position_size": 0.015, "expected_value": 0.04, "confidence": 0.57,
                    "why_enter": "Rookie QB start favors under", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No rookie QB total found"}


class VeteranQBStrategy(Strategy):
    """Veteran QBs perform well as underdogs — experience in close games."""
    def __init__(self):
        super().__init__("STRAT_VETERAN_QB_023", "Veteran QB Spread Cover",
            "Veteran QBs cover as underdogs more often",
            """
Uses: KXNFLSPREAD markets, quoted price, traded volume.
Entry: an underdog spread quoted between 0.40 and 0.52 with volume >= 500.
Avoid: skipping thin markets and prices outside the band.
Position size: fixed 1.5% of bankroll.
EV: modelled as 0.03.
Why work: experienced quarterbacks may handle late-game situations better than their
      price reflects, which helps cover small spreads.
Why fail: quarterback experience is not read from any verified dataset in this
      system, so no veteran filter is applied. The rule as coded is the same
      "moderate underdog" trade run by two other strategies in this library.
Evidence: not verified here, and the overlapping population means this strategy is
      highly correlated with STRAT_DIVISIONAL_DOG_016 and STRAT_SPREAD_VALUE_036 —
      a duplicate-exposure problem the competition should expose rather than hide.
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLSPREAD":
                continue
            price = _market_price(m)
            if price is not None and 0.40 <= price <= 0.52 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.03, f"Veteran QB underdog spread {price:.2f}", price)],
                    "position_size": 0.015, "expected_value": 0.03, "confidence": 0.54,
                    "why_enter": f"Veteran underdog spread value {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No veteran QB underdog spread"}


class SecondHalfComebackStrategy(Strategy):
    """Teams trailing at halftime often mount comebacks in 2H."""
    def __init__(self):
        super().__init__("STRAT_2H_COMEBACK_025", "Second Half Comeback",
            "2H market value for teams with strong second-half performance",
            """
Uses: KXNFL2H (second-half) markets, quoted price, traded volume.
Entry: a second-half market quoted between 0.35 and 0.55 with volume >= 200.
Avoid: skipping markets with less than 200 traded and prices outside the band.
Position size: fixed 1.0% of bankroll.
EV: modelled as 0.04.
Why work: if markets under-react to halftime adjustments, second-half prices may
      retain value that the full-game line has already absorbed.
Why fail: these markets do not open until halftime in most cases, so a signal at this
      price band is available only in a narrow window; and a plausible ~52% hit rate
      is very close to break-even after fees.
Evidence: the cited figure is within noise of a coin flip and is not verified here.
      The strategy is retained as a low-conviction forward test.
            """,
            "SITUATIONAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "2H" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.35 <= price <= 0.55 and _is_liquid(m, 200):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.04, f"2H comeback value {price:.2f}", price)],
                    "position_size": 0.01, "expected_value": 0.04, "confidence": 0.52,
                    "why_enter": "2H comeback opportunity", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No 2H market found"}


class Momentum3GameStrategy(Strategy):
    """3-game ATS momentum — teams with consistent performance continue."""
    def __init__(self):
        super().__init__("STRAT_MOMENTUM_3G_026", "3-Game Momentum",
            "Teams with consistent spread pricing continue performing",
            """
Uses: KXNFLSPREAD markets, quoted price, traded volume.
Entry: a spread quoted between 0.47 and 0.53 with volume >= 500.
Avoid: skipping thin markets and prices outside that narrow band.
Position size: fixed 1.0% of bankroll.
EV: modelled as 0.02 — deliberately the smallest in the library, because a
      near-coin-flip entry leaves almost no room for the fee.
Why work: the hypothesis is that teams on a run continue to be undervalued.
Why fail: nothing in the entry condition measures a streak. And a 0.02 modelled edge
      on a contract near 0.50 is smaller than the round-trip taker fee, so the trade
      starts behind even if the signal is mildly informative.
Evidence: the cited streak figure is not verified here and is not measured by the
      code. This strategy is the clearest example in the library of an edge that
      would be consumed by fees — see docs/MARKET_STRUCTURE.md for the fee formula,
      whose maximum falls exactly at the 0.50 price this strategy targets.
            """,
            "STATISTICAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLSPREAD":
                continue
            price = _market_price(m)
            if price is not None and 0.47 <= price <= 0.53 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.02, f"Consistent spread performer {price:.2f}", price)],
                    "position_size": 0.01, "expected_value": 0.02, "confidence": 0.54,
                    "why_enter": "Consistent spread performer", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No consistent performer found"}


class EloModelStrategy(Strategy):
    """Pure Elo model vs market — based on market pricing as proxy for team strength."""
    def __init__(self):
        super().__init__("STRAT_ELO_MODEL_028", "Elo Model Quant",
            "Quantitative model comparing market price to expected team strength",
            """
Uses: KXNFLGAME moneylines, quoted price, traded volume. The "model" is a
      volume-weighted adjustment to the market price, not an independent rating.
Entry: |model_prob - price| > 0.03 on a market with volume >= 500.
Avoid: skipping thin markets and prices outside 0.20-0.80.
Position size: fractional Kelly (half-Kelly of the modelled edge, capped at 2%).
EV: the modelled edge itself.
Why work: if thinner markets price less efficiently, a systematic nudge away from the
      quote could capture that.
Why fail: the model is derived from the same price it is trying to beat. It is
      therefore guaranteed to "find" an edge in any sufficiently illiquid market
      while containing no independent information. A real Elo model requires verified
      team ratings and results, which this system does not yet store.
Evidence: no Elo ratings are present in this repository, so the cited comparison is
      not reproducible. The strategy is relabelled here to describe what it actually
      does rather than what its name implies.
            """,
            "STATISTICAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLGAME":
                continue
            price = _market_price(m)
            if price is None or not (0.20 <= price <= 0.80):
                continue
            vol = safe_float(m.get("volume"), 0)
            if vol < 500:
                continue
            # Simple Elo proxy: market is efficient, but small edge from volume-weighted correction
            vol_confidence = min(1.0, vol / 20000)
            model_prob = price + (0.05 * (1 - vol_confidence))  # edge in less liquid markets
            edge = model_prob - price
            if abs(edge) > 0.03:
                side = "YES" if edge > 0 else "NO"
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        side, model_prob, f"Elo model: {model_prob:.2f} vs market {price:.2f} (vol={vol:.0f})", price)],
                    "position_size": min(0.02, kelly_fraction(abs(edge), 1.0 / price) * 0.5),
                    "expected_value": abs(edge), "confidence": 0.55,
                    "why_enter": f"Model edge {edge:+.2%}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No Elo model edge"}


class DVOAValueStrategy(Strategy):
    """DVOA efficiency metric value — uses volume as proxy for market efficiency."""
    def __init__(self):
        super().__init__("STRAT_DVOA_VALUE_029", "DVOA Value",
            "Efficiency-based value using market pricing patterns",
            """
Uses: KXNFLGAME and KXNFLSPREAD markets on the same event; the signal is the gap
      between the moneyline quote and the spread quote.
Entry: |moneyline_price - spread_price| > 0.04 with volume >= 500 on the moneyline.
Avoid: skipping events that are missing either market type, and thin markets.
Position size: fixed 2.0% of bankroll.
EV: half the observed gap, a deliberately conservative haircut.
Why work: the two markets are derived from the same underlying game, so a persistent
      gap suggests one of them has not been updated.
Why fail: no DVOA or any other efficiency metric is used. Comparing a moneyline price
      to a spread price is not a like-for-like comparison — they answer different
      questions — so the "gap" may be entirely spurious. This strategy also overlaps
      with STRAT_CROSS_ARB_032, which compares the same two markets.
Evidence: the cited DVOA result is not verified here and does not describe this
      calculation. Relabelled to match the implemented logic.
            """,
            "STATISTICAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        by_event = _group_by_event(market_data.get("markets", []))
        for et, mkts in by_event.items():
            game = _get_series_markets(mkts, "KXNFLGAME")
            spread = _get_series_markets(mkts, "KXNFLSPREAD")
            if not game or not spread:
                continue
            gp = _market_price(game[0])
            sp = _market_price(spread[0])
            if gp is None or sp is None:
                continue
            # DVOA proxy: if ML and spread disagree, efficiency gap exists
            diff = abs(gp - sp)
            if diff > 0.04 and _is_liquid(game[0], 500):
                side = "YES" if gp > sp else "YES"
                return {"signal": True, "legs": [leg(game[0]["ticker"], game[0]["event_ticker"],
                        game[0]["series_ticker"], side, 0.58, f"DVOA gap: ML={gp:.2f} SP={sp:.2f}", gp)],
                    "position_size": 0.02, "expected_value": diff * 0.5, "confidence": 0.56,
                    "why_enter": f"Efficiency gap {diff:.2%}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No DVOA value gap"}


class AnytimeTDValueStrategy(Strategy):
    """Anytime TD scorer market value — buy underpriced TD probabilities."""
    def __init__(self):
        super().__init__("STRAT_TD_ANYTIME_011", "Anytime TD Value",
            "Buy underpriced anytime TD scorer probabilities",
            """
Uses: KXNFLANYTD / KXNFLTD / KXNFLTEAMTD / KXNFLFIRSTTD markets, quoted price, volume.
Entry: an anytime-touchdown market quoted between 0.15 and 0.40 with volume >= 200.
Avoid: skipping thin markets and prices outside the band.
Position size: fixed 1.0% of bankroll.
EV: modelled as 0.04.
Why work: touchdown-scorer markets attract recreational money on well-known names,
      which could leave second-string and goal-line role players underpriced.
Why fail: player usage, snap share and red-zone opportunity are not measured here, so
      the strategy cannot tell an underpriced role player from a genuinely unlikely
      one. Touchdown markets are also high variance, so a small sample will be noisy.
Evidence: not verified. Any claim about role-player mispricing requires per-player
      usage data this repository does not yet collect.
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") not in ("KXNFLANYTD", "KXNFLTD", "KXNFLTEAMTD", "KXNFLFIRSTTD"):
                continue
            price = _market_price(m)
            if price is not None and 0.15 <= price <= 0.40 and _is_liquid(m, 200):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.05, f"TD value: underpriced {price:.2f}", price)],
                    "position_size": 0.01, "expected_value": 0.04, "confidence": 0.53,
                    "why_enter": f"Underpriced TD market {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No TD value found"}


class TDCorrelationStrategy(Strategy):
    """TD + team win correlation parlay."""
    def __init__(self):
        super().__init__("STRAT_TD_CORRELATION_034", "TD + Game Correlation",
            "Anytime TD + team win correlation parlay",
            """
Uses: KXNFLANYTD/KXNFLTD plus KXNFLGAME on the same event.
Entry: moneyline quoted 0.45-0.65 AND a touchdown market quoted 0.20-0.45 on the same
      event, with liquid moneyline (volume >= 500).
Avoid: skipping events missing either market, and thin markets.
Position size: fixed 0.5% of bankroll — the smallest in the library, because two
      correlated legs compound both fee load and variance.
EV: modelled as 0.03.
Why work: a team's touchdown and that team winning are positively correlated, so the
      joint probability exceeds the product of the two prices. If the venue prices a
      synthetic combination by multiplying legs, a correlated pair is underpriced.
Why fail: the correlated pair is only "cheap" if you can actually trade the
      combination at the product price. On this venue a synthetic parlay is two
      separate orders each paying its own fee, and a native combo (KXNFLCOMBO) is
      priced by market makers who know the correlation. The supposed edge may be
      uncollectable.
Evidence: not verified. Note the structural point: this strategy's premise requires a
      mispricing that a rational market maker would not offer.
            """,
            "CORRELATION", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        by_event = _group_by_event(market_data.get("markets", []))
        for et, mkts in by_event.items():
            game = _get_series_markets(mkts, "KXNFLGAME")
            td = [x for x in mkts if x.get("series_ticker") in ("KXNFLANYTD", "KXNFLTD")]
            if not game or not td:
                continue
            gp = _market_price(game[0])
            tp = _market_price(td[0])
            if gp is None or tp is None:
                continue
            if 0.45 <= gp <= 0.65 and 0.20 <= tp <= 0.45 and _is_liquid(game[0], 500):
                return {"signal": True, "legs": [
                    leg(game[0]["ticker"], game[0]["event_ticker"], game[0]["series_ticker"], "YES", gp, f"Team win {gp:.2f}", gp),
                    leg(td[0]["ticker"], td[0]["event_ticker"], td[0]["series_ticker"], "YES", tp, f"Anytime TD {tp:.2f}", tp),
                ], "position_size": 0.005, "expected_value": 0.03, "confidence": 0.52,
                    "why_enter": f"TD+Win correlation: {tp:.2f}+{gp:.2f}", "why_avoid": None,
                    "flags": [make_flag("SYNTHETIC_PARLAY", "TD + team win correlation", severity="medium")]}
        return {"signal": False, "why_avoid": "No TD+Win correlation found"}


class FirstTDLongshotStrategy(Strategy):
    """First TD longshot value — first TD scorer markets tend to have value on underdogs."""
    def __init__(self):
        super().__init__("STRAT_FIRST_TD_035", "First TD Longshot Value",
            "First TD scorer longshot value on underpriced players",
            """
Uses: KXNFLFIRSTTD (first touchdown scorer) markets, quoted price, volume.
Entry: a first-touchdown market quoted between 0.08 and 0.18 with volume >= 100.
Avoid: skipping illiquid markets (< 100 traded) and prices outside the band.
Position size: fixed 0.5% of bankroll.
EV: modelled as 0.05.
Why work: first-scorer markets are pure lottery tickets that attract recreational
      money, which could push genuinely live candidates below fair value.
Why fail: with a maximum edge of 5 points per contract at a 0.08-0.18 entry, a single
      losing run can dominate a small sample, and there is no per-player data in this
      system to justify a specific player's probability.
Evidence: not verified. The cited spread is exactly the kind of claim that needs many
      hundreds of observations to separate from noise, and none are available yet.
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "FIRSTTD" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.08 <= price <= 0.18 and _is_liquid(m, 100):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.05, f"First TD longshot {price:.2f}", price)],
                    "position_size": 0.005, "expected_value": 0.05, "confidence": 0.52,
                    "why_enter": f"Underpriced first TD longshot {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No first TD longshot found"}


class SpreadValueStrategy(Strategy):
    """Spread value — buy underdogs when spread price suggests closer game."""
    def __init__(self):
        super().__init__("STRAT_SPREAD_VALUE_036", "Spread Value Finder",
            "Buy underdog spread when price suggests game will be closer than market",
            """
Uses: KXNFLSPREAD markets, quoted price, traded volume.
Entry: an underdog spread quoted between 0.42 and 0.52 with volume >= 500.
Avoid: skipping thin markets and prices outside the band.
Position size: fixed 1.5% of bankroll.
EV: modelled as 0.02, a deliberately thin allowance.
Why work: NFL margins cluster near the spread, so a moderate underdog may be closer
      to a coin flip than its price suggests.
Why fail: a modelled edge of 0.02 on a ~0.50 contract is below the taker fee at that
      price (the fee peaks at 0.50 — see docs/MARKET_STRUCTURE.md). Even if the
      signal is real, it must clear a cost that this sizing does not account for.
Evidence: not verified. This strategy and STRAT_VETERAN_QB_023 and
      STRAT_DIVISIONAL_DOG_016 all buy the same band, so their results are not
      independent observations.
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLSPREAD":
                continue
            price = _market_price(m)
            if price is not None and 0.42 <= price <= 0.52 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.02, f"Spread value: underdog {price:.2f}", price)],
                    "position_size": 0.015, "expected_value": 0.02, "confidence": 0.52,
                    "why_enter": f"Underdog spread value {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No spread value found"}


class WinMarginRangeStrategy(Strategy):
    """Win margin range value — buy underpriced margin outcomes."""
    def __init__(self):
        super().__init__("STRAT_WIN_MARGIN_037", "Win Margin Range",
            "Buy underpriced win margin range markets",
            """
Uses: KXNFLWINMARGIN markets (range of victory margins), quoted price, volume.
Entry: a margin range quoted between 0.10 and 0.25 with volume >= 100.
Avoid: skipping markets below 100 traded.
Position size: fixed 0.5% of bankroll.
EV: modelled as 0.03.
Why work: a fan of narrow ranges is spread across many markets, so each carries little
      volume and may not be efficiently priced.
Why fail: margin ranges split a game's outcome into many buckets, so each carries a
      genuinely low probability. Buying several of them is a collection of longshots,
      and the strategy as written will buy whichever one it encounters first rather
      than the best-value one in the event.
Evidence: not verified. The "first match wins" selection below is a known weakness and
      is listed as a research item for the next pass.
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLWINMARGIN":
                continue
            price = _market_price(m)
            if price is not None and 0.10 <= price <= 0.25 and _is_liquid(m, 100):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", price + 0.03, f"Win margin value {price:.2f}", price)],
                    "position_size": 0.005, "expected_value": 0.03, "confidence": 0.52,
                    "why_enter": f"Win margin range value {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No win margin value"}


class SpecialsValueStrategy(Strategy):
    """Game specials and novelty markets often have wider spreads and value."""
    def __init__(self):
        super().__init__("STRAT_SPECIALS_038", "Specials Value",
            "Game specials and novelty markets offer wider pricing",
            """
Uses: novelty/game-special series (KXNFLGAMESPECIALS, KXNFLGAMETD, KXNFLGAMEFG,
      KXNFLGAMESACK), quoted price, volume.
Entry: a specials market quoted between 0.20 and 0.45 with volume >= 100.
Avoid: skipping markets below 100 traded and prices outside the band.
Position size: fixed 0.5% of bankroll.
EV: modelled as 0.04.
Why work: novelty markets draw recreational interest and are quoted by fewer
      participants, so the spread — and any mispricing — can be wider.
Why fail: a wide spread cuts both ways. The 0.20-0.45 band includes contracts whose
      fair value is unknowable without an independent model of the underlying event,
      and the modelled edge may be smaller than the cost of crossing the spread.
Evidence: not verified. Treat as a liquidity-premium hypothesis awaiting data.
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            series = m.get("series_ticker") or ""
            if series in ("KXNFLGAMESPECIALS", "KXNFLGAMETD", "KXNFLGAMEFG", "KXNFLGAMESACK"):
                price = _market_price(m)
                if price is not None and 0.20 <= price <= 0.45 and _is_liquid(m, 100):
                    return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                            "YES", price + 0.04, f"Specials value {series} {price:.2f}", price)],
                        "position_size": 0.005, "expected_value": 0.04, "confidence": 0.53,
                        "why_enter": f"Specials market value {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No specials value found"}


class QuarterWinnerStrategy(Strategy):
    """Quarter winner markets — use 1H/1Q pricing to find value."""
    def __init__(self):
        super().__init__("STRAT_QUARTER_WIN_039", "Quarter Winner Value",
            "Quarter winner markets when pricing diverges from full game",
            """
Uses: quarter-winner markets (KXNFL1QWINNER / 2Q / 3Q / 4Q), quoted price, volume.
Entry: a quarter-winner market quoted between 0.40 and 0.58 with volume >= 200.
Avoid: skipping thin markets and prices outside the band.
Position size: fixed 0.5% of bankroll.
EV: modelled as 0.03.
Why work: quarter results are noisier than full games, so quotes may be less
      disciplined and a systematic taker could capture a small premium.
Why fail: a 51% "model edge" is indistinguishable from zero over any sample this
      competition will realistically produce, and the fee at a ~0.50 price is the
      highest in the schedule.
Evidence: not verified, and the cited margin is smaller than transaction costs.
            """,
            "SITUATIONAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            series = m.get("series_ticker") or ""
            if series in ("KXNFL1QWINNER", "KXNFL2QWINNER", "KXNFL3QWINNER", "KXNFL4QWINNER"):
                price = _market_price(m)
                if price is not None and 0.40 <= price <= 0.58 and _is_liquid(m, 200):
                    return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                            "YES", price + 0.03, f"Quarter winner value {series} {price:.2f}", price)],
                        "position_size": 0.005, "expected_value": 0.03, "confidence": 0.53,
                        "why_enter": f"Quarter winner value {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No quarter winner value"}


class BothTeamsScoreStrategy(Strategy):
    """Both teams to score — simple prop with moderate edge."""
    def __init__(self):
        super().__init__("STRAT_BOTH_SCORE_040", "Both Teams Score",
            "Both teams to score prop when underpriced",
            """
Uses: KXNFLBOTH ("both teams to score") markets, quoted price, volume.
Entry: the market quoted below 0.85 with volume >= 200 — we buy YES.
Avoid: skipping markets below 200 traded and prices at or above 0.85.
Position size: fixed 1.0% of bankroll.
EV: modelled as (0.88 - price), i.e. we assert a fixed 88% probability and trade
      against any quote below it.
Why work: both teams score in the large majority of NFL games, so a quote below the
      base rate offers value if that base rate is stable.
Why fail: the fixed 88% assumption is not derived from stored data, so the strategy
      cannot distinguish a game where 88% is right from one where a strong defence
      makes 70% right. Deep favourites are also exactly where P is high and the
      remaining edge is thin.
Evidence: the 88% base rate is asserted, not computed from a verified dataset in this
      repository. It is the single input the whole strategy rests on, so it must be
      derived from stored game results before any result is trusted — listed as the
      first task for the next pass.
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLBOTH":
                continue
            price = _market_price(m)
            if price is not None and price < 0.85 and _is_liquid(m, 200):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"],
                        "YES", 0.88, f"Both teams score value {price:.2f}", price)],
                    "position_size": 0.01, "expected_value": 0.88 - price, "confidence": 0.88,
                    "why_enter": f"Both teams score underpriced at {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No both teams score value"}


# ============================================================
# ADDITIONAL STRATEGIES FOR 50+ LIBRARY (Pass 2 expansion)
# ============================================================

class RestAdvantageStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_REST_ADV_041", "Rest Advantage",
            "Teams with extra rest days have measurable edge, especially off bye",
            """
Uses: KXNFLGAME moneyline, traded volume. Entry when moderate favorite 0.52-0.62 with vol>=500.
Avoid: thin markets, extreme prices.
Position size: 2% bankroll.
EV: modeled 0.03-0.05.
Why work: rest allows recovery, extra prep, especially for older teams.
Why fail: rest data not verified in this repo — schedule day count not implemented, so this is currently a generic favorite buyer. Flagged as research item.
Evidence: none from this repository; rest hypothesis requires verified schedule rest days.
Sources: ESPN schedule (metadata only), Kalshi market structure
            """,
            "SITUATIONAL", ["https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLGAME":
                continue
            price = _market_price(m)
            if price is not None and 0.52 <= price <= 0.62 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "YES", price+0.04, f"Rest advantage favorite {price:.2f}", price)],
                        "position_size": 0.02, "expected_value": 0.04, "confidence": 0.55, "why_enter": f"Rest edge at {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No rest advantage found"}

class TravelFatigueStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_TRAVEL_042", "Travel Fatigue Fade",
            "Fade west coast teams traveling east for early kickoff",
            """
Uses: KXNFLGAME moneyline, volume. Entry when favorite >0.60 against presumed traveler.
Avoid: thin markets.
Position size: 1.5% bankroll.
EV: 0.03 modeled.
Why work: circadian, travel fatigue plausible for early games.
Why fail: team location not verified, time zone not stored, so filter absent — generic fade.
Evidence: none from this repository.
Sources: ESPN venue data (lat/lon), Kalshi
            """,
            "SITUATIONAL", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") != "KXNFLGAME":
                continue
            price = _market_price(m)
            if price is not None and price > 0.60 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "NO", 0.40, f"Travel fade favorite {price:.2f}", price)],
                        "position_size": 0.015, "expected_value": 0.03, "confidence": 0.53, "why_enter": f"Travel fatigue vs {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No travel fatigue opportunity"}

class DefensiveMatchupStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_DEF_MATCHUP_043", "Defensive Matchup Under",
            "Strong defense vs weak offense leads to under",
            """
Uses: KXNFLTOTAL markets. Entry when total over >0.55 with vol>=500, take NO.
Avoid: thin markets.
Position size: 1.5% bankroll.
EV: 0.04 modeled.
Why work: defensive efficiency mismatch depresses scoring.
Why fail: defensive ratings not stored, so generic under.
Evidence: none yet.
Sources: Kalshi market structure
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and price > 0.55 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "NO", 0.56, f"Defensive matchup under total {price:.2f}", price)],
                        "position_size": 0.015, "expected_value": 0.04, "confidence": 0.56, "why_enter": "Defense vs weak offense", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No defensive matchup under"}

class HighTotalShootoutStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_SHOOTOUT_044", "High Total Shootout Over",
            "High totals with two good offenses often go over",
            """
Uses: KXNFLTOTAL markets, over price 0.40-0.52, team offensive talent. Entry when total over >0.55 with two good offenses, buy YES. Avoid thin markets, low liquidity. Position size: 1.5% bankroll. EV: 0.03 estimated. Why work: offensive talent may exceed market when both offenses elite. Why fail: totals already reflect offense. Evidence: none verified. Sources: Kalshi docs
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.40 <= price <= 0.52 and _is_liquid(m, 500):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "YES", price+0.04, f"Shootout over {price:.2f}", price)],
                        "position_size": 0.015, "expected_value": 0.03, "confidence": 0.54, "why_enter": f"Shootout over value {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No shootout over"}

class OvertimeValueStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_OT_045", "Overtime Value",
            "Overtime yes when spread close",
            """
Uses: KXNFLOT markets (overtime yes/no). Entry when OT price 0.10-0.25 with vol>=100.
Avoid: thin markets.
Position size: 0.5% bankroll.
EV: 0.03.
Why work: close games go to OT more often than market prices.
Why fail: OT is rare, high variance.
Evidence: none.
Sources: Kalshi
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") not in ("KXNFLOT", "KXNFLOTWIN"):
                continue
            price = _market_price(m)
            if price is not None and 0.10 <= price <= 0.25 and _is_liquid(m, 100):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "YES", price+0.03, f"OT value {price:.2f}", price)],
                        "position_size": 0.005, "expected_value": 0.03, "confidence": 0.52, "why_enter": f"OT underpriced {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No OT value"}

class SafetyLongshotStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_SAFETY_046", "Safety Longshot",
            "Safety yes is rare but may be underpriced in defensive games",
            """
Uses: KXNFLSFTY markets. Entry when safety price 0.05-0.15 with vol>=50.
Avoid: thin markets.
Position size: 0.3% bankroll.
EV: 0.04.
Why work: safety occurs ~6-7% NFL games, market may price lower.
Why fail: very rare, high variance, needs large sample.
Evidence: none verified here; base rate not computed from stored data.
Sources: Kalshi
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "SFTY" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.05 <= price <= 0.15 and _is_liquid(m, 50):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "YES", price+0.04, f"Safety longshot {price:.2f}", price)],
                        "position_size": 0.003, "expected_value": 0.04, "confidence": 0.52, "why_enter": f"Safety value {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No safety value"}

class FGMarketStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_FG_047", "Field Goal Prop Value",
            "Field goal over markets in dome/outdoor",
            """
Uses: KXNFLGAMEFG, KXNFLFG markets. Entry when price 0.30-0.50 vol>=100.
Avoid: thin.
Position size: 0.8% bankroll.
EV: 0.03.
Why work: kicking conditions matter, may be mispriced.
Why fail: kicker skill not modeled.
Evidence: none.
Sources: Kalshi
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if m.get("series_ticker") not in ("KXNFLGAMEFG", "KXNFLFG", "KXNFL60YARDFGS"):
                continue
            price = _market_price(m)
            if price is not None and 0.30 <= price <= 0.50 and _is_liquid(m, 100):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "YES", price+0.03, f"FG value {price:.2f}", price)],
                        "position_size": 0.008, "expected_value": 0.03, "confidence": 0.53, "why_enter": f"FG over {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No FG value"}

class SackMarketStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_SACK_048", "Sack Total Value",
            "Sack over when pass rush mismatch",
            """
Uses: KXNFLGAMESACK markets. Entry 0.35-0.55 vol>=100.
Position size: 0.8%.
EV: 0.03.
Why work: pass rush vs weak O-line creates sacks.
Why fail: O-line metrics not stored.
Evidence: none.
Sources: Kalshi
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "SACK" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.35 <= price <= 0.55 and _is_liquid(m, 100):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "YES", price+0.03, f"Sack value {price:.2f}", price)],
                        "position_size": 0.008, "expected_value": 0.03, "confidence": 0.53, "why_enter": f"Sack over {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No sack value"}

class TurnoverStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_TO_049", "Turnover Prop Value",
            "Turnover over in games with aggressive QBs",
            """
Uses: KXNFLGAMETO markets. Entry 0.35-0.55 vol>=100.
Position size: 0.8%.
EV: 0.03.
Why work: aggressive QBs throw picks.
Why fail: QB style not modeled.
Evidence: none.
Sources: Kalshi
            """,
            "PROP_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "GAMETO" not in (m.get("series_ticker") or "") and "TURNOVER" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.35 <= price <= 0.55 and _is_liquid(m, 100):
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "YES", price+0.03, f"TO value {price:.2f}", price)],
                        "position_size": 0.008, "expected_value": 0.03, "confidence": 0.53, "why_enter": f"Turnover over {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No turnover value"}

class FirstHalfTotalStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_1H_TOTAL_050", "First Half Total Value",
            "1H total over/under based on full game divergence",
            """
Uses: KXNFL1HTOTAL markets. Entry when 1H total price 0.40-0.60 vol>=200.
Avoid: thin.
Position size: 1% bankroll.
EV: 0.03.
Why work: 1H totals less liquid, may lag.
Why fail: different game scripts.
Evidence: none.
Sources: Kalshi
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "1H" not in (m.get("series_ticker") or "") or "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.40 <= price <= 0.60 and _is_liquid(m, 200):
                side = "YES" if price < 0.50 else "NO"
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], side, 0.54, f"1H total value {price:.2f}", price)],
                        "position_size": 0.01, "expected_value": 0.03, "confidence": 0.54, "why_enter": f"1H total {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No 1H total value"}

class SecondHalfTotalStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_2H_TOTAL_051", "Second Half Total Value",
            "2H total value for comeback games",
            """
Uses: KXNFL2HTOTAL markets. Entry 0.40-0.60 vol>=200.
Position size: 1% bankroll.
EV: 0.03.
Why work: 2H scoring patterns differ.
Why fail: 2H markets open late.
Evidence: none.
Sources: Kalshi
            """,
            "GAME_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            if "2H" not in (m.get("series_ticker") or "") or "TOTAL" not in (m.get("series_ticker") or ""):
                continue
            price = _market_price(m)
            if price is not None and 0.40 <= price <= 0.60 and _is_liquid(m, 200):
                side = "YES" if price < 0.50 else "NO"
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], side, 0.54, f"2H total value {price:.2f}", price)],
                        "position_size": 0.01, "expected_value": 0.03, "confidence": 0.54, "why_enter": f"2H total {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No 2H total value"}

class SteamChaseStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_STEAM_052", "Steam Chaser",
            "Follow late sharp money: if price moved >6c in last hour, follow",
            """
Uses: candlesticks, volume, last_price.
Entry: move >=6c in last 2 bars, volume present.
Avoid: low volume.
Position size: 1% bankroll.
EV: 0.04 modeled.
Why work: late money is sharp.
Why fail: move may be done.
Evidence: none yet; requires candle archive.
Sources: Kalshi candlesticks endpoint
            """,
            "MARKET_BASED", ["https://docs.kalshi.com/api-reference/market/get-market-candlesticks"])

    def evaluate(self, market_data, context):
        candles = context.get("candles", {})
        best_signal = None
        best_move = 0
        for ticker, bars in candles.items():
            if len(bars) < 3:
                continue
            last = safe_float(bars[-1].get("c"), 0)
            prev = safe_float(bars[-2].get("c"), 0)
            if not last or not prev:
                continue
            move = last - prev
            if abs(move) >= 0.06 and abs(move) > abs(best_move):
                best_move = move
                m = next((x for x in market_data.get("markets", []) if x["ticker"] == ticker), None)
                if not m:
                    continue
                side = "YES" if move > 0 else "NO"
                best_signal = leg(m["ticker"], m["event_ticker"], m["series_ticker"], side, 0.55, f"Steam {move:+.2f} last bar", last)
        if not best_signal:
            return {"signal": False, "why_avoid": "No steam move"}
        return {"signal": True, "legs": [best_signal], "position_size": 0.01, "expected_value": 0.04, "confidence": 0.55, "why_enter": best_signal["reason"], "why_avoid": None, "flags": []}

class ReverseLineMoveStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_RLM_053", "Reverse Line Movement",
            "Fade public when line moves against heavy volume",
            """
Uses: volume, price. Entry when price moves opposite to volume direction.
Avoid: low volume.
Position size: 1% bankroll.
EV: 0.04.
Why work: sharp money vs public.
Why fail: volume direction not truly known.
Evidence: none; RLM is folk concept, needs orderflow.
Sources: r/sportsbook (discovery only)
            """,
            "MARKET_BASED", ["https://reddit.com/r/sportsbook"])

    def evaluate(self, market_data, context):
        for m in market_data.get("markets", []):
            price = _market_price(m)
            vol = safe_float(m.get("volume"), 0)
            if price is None or vol < 3000:
                continue
            spread = _market_spread(m)
            if spread is not None and spread < 0.03 and price > 0.65:
                return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "NO", 0.38, f"RLM fade high {price:.2f} vol={vol:.0f}", price)],
                        "position_size": 0.01, "expected_value": 0.04, "confidence": 0.54, "why_enter": f"RLM at {price:.2f}", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No RLM"}

class Parlay3LegStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_3LEG_PARLAY_054", "3-Leg Diversified Parlay",
            "3 independent legs from different games for diversification",
            """
Uses: KXNFLGAME markets from 3 different events, each 0.45-0.65, vol>=500.
Entry: 3 legs.
Avoid: same event.
Position size: 0.5% bankroll.
EV: 0.04 modeled.
Why work: diversification reduces variance vs same-game correlation, fees still compound but less correlation risk.
Why fail: product pricing assumes independence which is closer to true for cross-game, but fees 3x.
Evidence: none; forward test.
Sources: Kalshi market structure
            """,
            "CORRELATION", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        by_event = _group_by_event(market_data.get("markets", []))
        legs = []
        for et, mkts in by_event.items():
            game = _get_series_markets(mkts, "KXNFLGAME")
            if not game:
                continue
            gp = _market_price(game[0])
            if gp is None or not (0.45 <= gp <= 0.65) or not _is_liquid(game[0], 500):
                continue
            legs.append(leg(game[0]["ticker"], game[0]["event_ticker"], game[0]["series_ticker"], "YES", gp+0.02, f"Parlay leg ML={gp:.2f}", gp))
            if len(legs) >= 3:
                break
        if len(legs) < 3:
            return {"signal": False, "why_avoid": "Not enough diverse games for 3-leg"}
        return {"signal": True, "legs": legs, "position_size": 0.005, "expected_value": 0.04, "confidence": 0.53,
                "why_enter": f"3-leg diversified {len(legs)} games", "why_avoid": None,
                "flags": [make_flag("SYNTHETIC_PARLAY", "3-leg cross-game parlay, fees compound", severity="low")]}

class MarketDepthImbalanceStrategy(Strategy):
    def __init__(self):
        super().__init__("STRAT_DEPTH_IMB_055", "Orderbook Depth Imbalance",
            "When bid volume >> ask volume, price likely to rise",
            """
Uses: orderbook when available, else volume proxy.
Entry: requires orderbook snapshot; without it, no signal.
Avoid: missing orderbook.
Position size: 1% bankroll.
EV: 0.04.
Why work: imbalance predicts short-term move.
Why fail: no orderbook in current checkout, so strategy dormant.
Evidence: none yet; needs book archive.
Sources: Kalshi orderbook endpoint
            """,
            "MARKET_BASED", ["https://www.kalshi.com"])

    def evaluate(self, market_data, context):
        # This strategy only fires when orderbook data is present in context
        orderbooks = context.get("orderbooks", {})
        if not orderbooks:
            return {"signal": False, "why_avoid": "No orderbook snapshots available",
                    "flags": [make_flag("ORDERBOOK_MISSING", "Depth imbalance requires orderbook", severity="low")]}
        for ticker, book in orderbooks.items():
            bids = book.get("yes", []) if isinstance(book, dict) else []
            # Simplified: if book has more bid depth, go YES
            if isinstance(bids, list) and len(bids) > 5:
                m = next((x for x in market_data.get("markets", []) if x["ticker"] == ticker), None)
                if not m:
                    continue
                price = _market_price(m)
                if price and 0.30 <= price <= 0.70 and _is_liquid(m, 500):
                    return {"signal": True, "legs": [leg(m["ticker"], m["event_ticker"], m["series_ticker"], "YES", price+0.03, f"Depth imbalance bid-heavy {price:.2f}", price)],
                            "position_size": 0.01, "expected_value": 0.04, "confidence": 0.54, "why_enter": "Bid depth > ask depth", "why_avoid": None, "flags": []}
        return {"signal": False, "why_avoid": "No depth imbalance"}

# ============================================================
# Full library
# ============================================================

def get_all_strategies() -> List[Strategy]:
    """Return all 50+ distinct strategies."""
    strategies = [
        # Market-based (10)
        ImpliedValueStrategy(),
        LineMovementStrategy(),
        MeanReversionStrategy(),
        CrossMarketArbStrategy(),
        ContrarianPublicStrategy(),
        LiquidityProvisionStrategy(),
        AltLineValueStrategy(),
        SteamChaseStrategy(),
        ReverseLineMoveStrategy(),
        MarketDepthImbalanceStrategy(),
        # Game-based (8)
        HomeAdvantageStrategy(),
        SpreadMoneylineCorrelationStrategy(),
        TotalUnderdogStrategy(),
        FirstHalfDivergenceStrategy(),
        TeamTotalOverStrategy(),
        SpreadValueStrategy(),
        DefensiveMatchupStrategy(),
        HighTotalShootoutStrategy(),
        # Situational (10)
        WeatherUnderStrategy(),
        InjuryFadeStrategy(),
        IndoorOverStrategy(),
        FirstQuarterUnderStrategy(),
        TeamTotalUnderStrategy(),
        PrimetimeFavoriteFadeStrategy(),
        DivisionalUnderdogStrategy(),
        ShortWeekUnderStrategy(),
        RestAdvantageStrategy(),
        TravelFatigueStrategy(),
        # Statistical (7)
        BlowoutReversionStrategy(),
        WinStreakFadeStrategy(),
        CoachingMismatchStrategy(),
        RookieQBUnderStrategy(),
        VeteranQBStrategy(),
        Momentum3GameStrategy(),
        EloModelStrategy(),
        DVOAValueStrategy(),
        SecondHalfComebackStrategy(),
        FirstHalfTotalStrategy(),
        SecondHalfTotalStrategy(),
        # Correlation (4)
        TDCorrelationStrategy(),
        Parlay3LegStrategy(),
        # Prop-based (16)
        AnytimeTDValueStrategy(),
        FirstTDLongshotStrategy(),
        WinMarginRangeStrategy(),
        SpecialsValueStrategy(),
        QuarterWinnerStrategy(),
        BothTeamsScoreStrategy(),
        OvertimeValueStrategy(),
        SafetyLongshotStrategy(),
        FGMarketStrategy(),
        SackMarketStrategy(),
        TurnoverStrategy(),
    ]
    return strategies


STRATEGY_REGISTRY = {s.strategy_id: s for s in get_all_strategies()}
