import unittest, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.execution import check_market_executable, simulate_execution

class TestExecution(unittest.TestCase):
    def test_executable(self):
        market = {
            "ticker": "KXNFLGAME-26SEP20CLETB-TB",
            "status": "active",
            "yes_bid": 0.58,
            "yes_ask": 0.62,
            "last_price": 0.6,
            "volume": 10000,
            "liquidity": 5000,
        }
        leg = {"market_ticker": "KXNFLGAME-26SEP20CLETB-TB", "entry_price": 0.6}
        ok, flags, details = check_market_executable(market, leg, quantity=10, side="YES")
        self.assertTrue(ok)
        self.assertIn("exec_price", details)

    def test_reject_closed(self):
        market = {
            "ticker": "KXNFLGAME-26SEP20CLETB-TB",
            "status": "closed",
            "yes_bid": 0.58,
            "yes_ask": 0.62,
            "last_price": 0.6,
        }
        leg = {"market_ticker": "KXNFLGAME-26SEP20CLETB-TB", "entry_price": 0.6}
        ok, flags, details = check_market_executable(market, leg, quantity=10, side="YES")
        self.assertFalse(ok)

    def test_simulate_execution(self):
        market_snapshots = {
            "KXNFLGAME-26SEP20CLETB-TB": {
                "ticker": "KXNFLGAME-26SEP20CLETB-TB",
                "status": "active",
                "yes_bid": 0.58,
                "yes_ask": 0.62,
                "last_price": 0.6,
                "volume": 10000,
                "liquidity": 5000,
            }
        }
        trade = {
            "trade_id": "t1",
            "user_id": "u1",
            "username": "test",
            "strategy_id": "STRAT_TEST",
            "status": "ORDER",
            "legs": [
                {"market_ticker": "KXNFLGAME-26SEP20CLETB-TB", "event_ticker": "KXNFLGAME-26SEP20CLETB", "series_ticker": "KXNFLGAME", "side": "YES", "entry_price": 0.6, "quantity": 10}
            ],
            "position_size_dollars": 6.0,
            "flags": [],
            "official_sources": [],
        }
        result = simulate_execution(trade, market_snapshots)
        self.assertEqual(result["status"], "EXECUTED")

if __name__ == "__main__":
    unittest.main()
