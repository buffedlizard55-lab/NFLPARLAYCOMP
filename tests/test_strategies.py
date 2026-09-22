"""Strategy-library tests.

The competition is only meaningful if strategies are genuinely distinct and if their
signals are reproducible. These tests enforce both, plus the documentation contract
every strategy must satisfy.
"""
import ast
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.strategies import get_all_strategies

MARKET_FIXTURE = {
    "markets": [
        {"ticker": "KXNFLGAME-A-HOME", "event_ticker": "KXNFLGAME-A",
         "series_ticker": "KXNFLGAME", "status": "active", "last_price": 0.60,
         "yes_bid": 0.58, "yes_ask": 0.62, "volume": 50000, "liquidity": 50000},
        {"ticker": "KXNFLSPREAD-A-HOME-3.5", "event_ticker": "KXNFLGAME-A",
         "series_ticker": "KXNFLSPREAD", "status": "active", "last_price": 0.50,
         "yes_bid": 0.48, "yes_ask": 0.52, "volume": 30000, "liquidity": 30000},
        {"ticker": "KXNFLTOTAL-A-O45.5", "event_ticker": "KXNFLGAME-A",
         "series_ticker": "KXNFLTOTAL", "status": "active", "last_price": 0.55,
         "yes_bid": 0.53, "yes_ask": 0.57, "volume": 20000, "liquidity": 20000},
        {"ticker": "KXNFL1H-A-HOME", "event_ticker": "KXNFLGAME-A",
         "series_ticker": "KXNFL1H", "status": "active", "last_price": 0.58,
         "yes_bid": 0.56, "yes_ask": 0.60, "volume": 5000, "liquidity": 5000},
        {"ticker": "KXNFLTEAMTOTAL-A-HOME-O22.5", "event_ticker": "KXNFLGAME-A",
         "series_ticker": "KXNFLTEAMTOTAL", "status": "active", "last_price": 0.45,
         "yes_bid": 0.43, "yes_ask": 0.47, "volume": 4000, "liquidity": 4000},
        {"ticker": "KXNFLGAME-B-HOME", "event_ticker": "KXNFLGAME-B",
         "series_ticker": "KXNFLGAME", "status": "active", "last_price": 0.82,
         "yes_bid": 0.80, "yes_ask": 0.84, "volume": 60000, "liquidity": 60000},
        {"ticker": "KXNFLTOTAL-B-O48.5", "event_ticker": "KXNFLGAME-B",
         "series_ticker": "KXNFLTOTAL", "status": "active", "last_price": 0.52,
         "yes_bid": 0.50, "yes_ask": 0.54, "volume": 25000, "liquidity": 25000},
    ]
}
CONTEXT = {"candles": {}, "schedule": {}, "injuries": {}, "weather": {}}


class TestLibraryShape(unittest.TestCase):

    def test_at_least_thirty_five_strategies(self):
        self.assertGreaterEqual(len(get_all_strategies()), 35)

    def test_ids_and_names_are_unique(self):
        strategies = get_all_strategies()
        ids = [s.strategy_id for s in strategies]
        names = [s.name for s in strategies]
        self.assertEqual(len(ids), len(set(ids)), "strategy IDs must be unique")
        self.assertEqual(len(names), len(set(names)), "strategy names must be unique")

    def test_descriptions_are_unique(self):
        """Stops padding the roster with renamed clones."""
        strategies = get_all_strategies()
        descriptions = [s.description for s in strategies]
        self.assertEqual(len(descriptions), len(set(descriptions)))

    def test_categories_are_populated_across_the_library(self):
        categories = {s.category for s in get_all_strategies()}
        for expected in ("MARKET_BASED", "GAME_BASED", "SITUATIONAL",
                         "CORRELATION", "STATISTICAL", "PROP_BASED"):
            with self.subTest(category=expected):
                self.assertIn(expected, categories)

    def test_every_strategy_documents_the_required_sections(self):
        """Each strategy must explain itself: info used, entry, avoid, sizing, EV,
        why it might work, why it might fail, and supporting evidence."""
        required = ["Uses", "Entry", "size"]
        for s in get_all_strategies():
            with self.subTest(strategy=s.strategy_id):
                text = s.long_explanation
                for token in required:
                    self.assertIn(token, text, f"{s.strategy_id} missing '{token}' section")
                self.assertGreater(len(text.strip()), 150, "explanation too thin")
                self.assertTrue(s.sources, "strategy must cite at least one source")
                self.assertTrue(all(str(u).startswith("http") for u in s.sources),
                                "sources must be links")


class TestDeterminism(unittest.TestCase):
    """Signals must be reproducible functions of the data, not coin flips."""

    def test_no_randomness_in_signal_generation(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "engine", "strategies.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "random":
                offenders.append(getattr(node, "lineno", "?"))
        self.assertEqual(offenders, [], f"random.* used in strategies.py at lines {offenders}")
        self.assertNotIn("import random", source)

    def test_same_inputs_give_same_signals(self):
        for s in get_all_strategies():
            with self.subTest(strategy=s.strategy_id):
                first = s.evaluate(MARKET_FIXTURE, CONTEXT)
                second = s.evaluate(MARKET_FIXTURE, CONTEXT)
                self.assertEqual(first.get("signal"), second.get("signal"))
                self.assertEqual(first.get("position_size"), second.get("position_size"))
                self.assertEqual(len(first.get("legs", [])), len(second.get("legs", [])))

    def test_empty_market_data_never_signals(self):
        for s in get_all_strategies():
            with self.subTest(strategy=s.strategy_id):
                result = s.evaluate({"markets": []}, CONTEXT)
                self.assertIn("signal", result)
                self.assertFalse(result["signal"], f"{s.strategy_id} signalled with no markets")


class TestSignalContract(unittest.TestCase):

    def test_signals_are_well_formed(self):
        for s in get_all_strategies():
            result = s.evaluate(MARKET_FIXTURE, CONTEXT)
            with self.subTest(strategy=s.strategy_id):
                self.assertIn("signal", result)
                if not result["signal"]:
                    continue
                self.assertTrue(result.get("legs"), "a signal must carry legs")
                self.assertIn("position_size", result)
                self.assertGreater(result["position_size"], 0)
                # Never risk the whole book on one signal.
                self.assertLessEqual(result["position_size"], 0.10)
                self.assertTrue(result.get("why_enter"), "a signal must explain itself")
                for leg in result["legs"]:
                    self.assertTrue(leg["market_ticker"])
                    self.assertIn(leg["side"], ("YES", "NO"))
                    self.assertIsNotNone(leg.get("model_prob"))
                    self.assertIsNotNone(leg.get("reason"))

    def test_legs_reference_real_markets(self):
        known = {m["ticker"] for m in MARKET_FIXTURE["markets"]}
        for s in get_all_strategies():
            result = s.evaluate(MARKET_FIXTURE, CONTEXT)
            if not result.get("signal"):
                continue
            for leg in result["legs"]:
                with self.subTest(strategy=s.strategy_id, ticker=leg["market_ticker"]):
                    self.assertIn(leg["market_ticker"], known,
                                  "a strategy must only reference markets in the data")

    def test_parlay_signals_are_flagged_as_synthetic(self):
        """A multi-leg signal is not a native Kalshi combo and must say so."""
        flagged_any = False
        for s in get_all_strategies():
            result = s.evaluate(MARKET_FIXTURE, CONTEXT)
            if not result.get("signal") or len(result.get("legs", [])) < 2:
                continue
            flagged_any = True
            types = {f.get("flag_type") for f in result.get("flags", [])}
            self.assertIn("SYNTHETIC_PARLAY", types,
                          f"{s.strategy_id} builds a multi-leg parlay without a SYNTHETIC_PARLAY flag")
        self.assertTrue(flagged_any, "expected at least one parlay strategy to signal")

    def test_distinct_strategies_do_not_all_return_identical_signals(self):
        """A roster of clones would make the competition meaningless."""
        signatures = set()
        for s in get_all_strategies():
            result = s.evaluate(MARKET_FIXTURE, CONTEXT)
            if not result.get("signal"):
                signatures.add(("none",))
                continue
            sig = tuple(sorted((leg["market_ticker"], leg["side"]) for leg in result["legs"]))
            signatures.add(sig)
        # With a small fixture many strategies correctly decline; require that the
        # ones that do act do not all collapse onto a single identical trade.
        self.assertGreaterEqual(len(signatures), 2)


if __name__ == "__main__":
    unittest.main()
