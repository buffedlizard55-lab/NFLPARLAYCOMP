import unittest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.parlay import combined_probability, price_parlay_synthetic, settle_parlay

class TestParlay(unittest.TestCase):
    def test_combined_probability(self):
        legs = [{"implied_prob": 0.6}, {"implied_prob": 0.5}]
        prob = combined_probability(legs)
        self.assertAlmostEqual(prob, 0.3)

    def test_synthetic_pricing(self):
        legs = [
            {"market_ticker": "KXNFLGAME-26SEP20CLETB-TB", "event_ticker": "KXNFLGAME-26SEP20CLETB", "implied_prob": 0.6, "entry_price": 0.6},
            {"market_ticker": "KXNFLSPREAD-26SEP20CLETB-TB-3.5", "event_ticker": "KXNFLGAME-26SEP20CLETB", "implied_prob": 0.55, "entry_price": 0.55},
        ]
        result = price_parlay_synthetic(legs, quantity=10)
        self.assertIn("combined_price", result)
        self.assertAlmostEqual(result["combined_price"], 0.33, places=2)

    def test_settle_win(self):
        trade = {
            "legs": [
                {"market_ticker": "KXNFLGAME-26SEP20CLETB-TB", "side": "YES", "quantity": 10},
            ],
            "entry_price_combined": 0.6,
            "fees": 0.0,
        }
        results = {"KXNFLGAME-26SEP20CLETB-TB": "yes"}
        settlement = settle_parlay(trade, results)
        self.assertEqual(settlement["result"], "WIN")

    def test_settle_loss(self):
        trade = {
            "legs": [
                {"market_ticker": "KXNFLGAME-26SEP20CLETB-TB", "side": "YES", "quantity": 10},
            ],
            "entry_price_combined": 0.6,
            "fees": 0.0,
        }
        results = {"KXNFLGAME-26SEP20CLETB-TB": "no"}
        settlement = settle_parlay(trade, results)
        self.assertEqual(settlement["result"], "LOSS")

if __name__ == "__main__":
    unittest.main()
