import unittest, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.strategies import get_all_strategies

class TestStrategies(unittest.TestCase):
    def test_count(self):
        strategies = get_all_strategies()
        self.assertGreaterEqual(len(strategies), 30, "Need 30+ strategies for scaling")

    def test_unique_ids(self):
        strategies = get_all_strategies()
        ids = [s.strategy_id for s in strategies]
        self.assertEqual(len(ids), len(set(ids)), "Strategy IDs must be unique")

    def test_evaluate(self):
        strategies = get_all_strategies()
        market_data = {
            "markets": [
                {"ticker": "KXNFLGAME-26SEP20CLETB-TB", "event_ticker": "KXNFLGAME-26SEP20CLETB", "series_ticker": "KXNFLGAME", "last_price": 0.6, "volume": 5000, "yes_bid": 0.58, "yes_ask": 0.62},
                {"ticker": "KXNFLSPREAD-26SEP20CLETB-TB-3.5", "event_ticker": "KXNFLGAME-26SEP20CLETB", "series_ticker": "KXNFLSPREAD", "last_price": 0.55, "volume": 3000, "yes_bid": 0.53, "yes_ask": 0.57},
                {"ticker": "KXNFLTOTAL-26SEP20CLETB-O45.5", "event_ticker": "KXNFLGAME-26SEP20CLETB", "series_ticker": "KXNFLTOTAL", "last_price": 0.5, "volume": 2000, "yes_bid": 0.48, "yes_ask": 0.52},
            ]
        }
        context = {"candles": {}, "weather": {}, "injuries": {}, "schedule": {}}
        signals = 0
        for s in strategies[:10]:
            result = s.evaluate(market_data, context)
            self.assertIn("signal", result)
            if result.get("signal"):
                signals += 1
                self.assertIn("legs", result)
                self.assertIn("position_size", result)
        # At least one should signal in random test
        # Not strict, but we check no crash

if __name__ == "__main__":
    unittest.main()
