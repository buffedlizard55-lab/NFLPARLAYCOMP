"""Execution-realism tests: quoting, depth, slippage, rejection.

Order-book fixtures below are hand-written in Kalshi's documented payload shape.
They are TEST FIXTURES, not market data: nothing here is presented as a real quote.
"""
import unittest, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.execution import check_market_executable, simulate_execution, simulate_close
from engine.orderbook import walk_book, ask_levels, book_depth_dollars


def market(ticker="KXNFLGAME-26SEP20CLETB-TB", bid=0.58, ask=0.62, last=0.60,
           volume=100000, status="active", **extra):
    base = {
        "ticker": ticker,
        "event_ticker": "KXNFLGAME-26SEP20CLETB",
        "series_ticker": "KXNFLGAME",
        "status": status,
        "yes_bid": bid,
        "yes_ask": ask,
        "last_price": last,
        "volume": volume,
        "liquidity": volume,
    }
    base.update(extra)
    return base


def leg(ticker="KXNFLGAME-26SEP20CLETB-TB", side="YES", price=0.60, quantity=10,
        series="KXNFLGAME"):
    return {"market_ticker": ticker, "event_ticker": "KXNFLGAME-26SEP20CLETB",
            "series_ticker": series, "side": side, "entry_price": price,
            "quantity": quantity}


class TestOrderBook(unittest.TestCase):
    """Book maths, using the documented Kalshi payload shape."""

    def test_yes_asks_are_one_minus_no_bids(self):
        book = {"orderbook": {"yes": [[58, 100], [55, 200]],
                              "no": [[40, 300], [35, 500]]}}
        asks = ask_levels(book, "YES")
        # Buying YES consumes NO bids: 1 - 0.40 = 0.60 first, then 1 - 0.35 = 0.65
        self.assertAlmostEqual(asks[0][0], 0.60, places=6)
        self.assertAlmostEqual(asks[1][0], 0.65, places=6)
        self.assertAlmostEqual(asks[0][1], 300, places=6)

    def test_no_asks_are_one_minus_yes_bids(self):
        book = {"orderbook": {"yes": [[58, 100]], "no": [[40, 300]]}}
        asks = ask_levels(book, "NO")
        # Buying NO consumes YES bids: 1 - 0.58 = 0.42
        self.assertAlmostEqual(asks[0][0], 0.42, places=6)

    def test_fixed_point_dollar_shape_is_accepted(self):
        book = {"orderbook_fp": {"yes_dollars": [["0.5800", "100.00"]],
                                 "no_dollars": [["0.4000", "300.00"]]}}
        asks = ask_levels(book, "YES")
        self.assertAlmostEqual(asks[0][0], 0.60, places=6)

    def test_single_level_fill_has_no_slippage(self):
        book = {"orderbook": {"no": [[40, 300]]}}
        fill = walk_book(book, "YES", 100)
        self.assertTrue(fill["depth_sufficient"])
        self.assertAlmostEqual(fill["average_price"], 0.60, places=6)
        self.assertAlmostEqual(fill["slippage_vs_best"], 0.0, places=6)

    def test_walking_levels_raises_average_price(self):
        book = {"orderbook": {"no": [[40, 100], [38, 100], [36, 100]]}}
        # YES asks: 0.60 (100), 0.62 (100), 0.64 (100)
        fill = walk_book(book, "YES", 250)
        self.assertTrue(fill["depth_sufficient"])
        self.assertEqual(fill["levels_consumed"], 3)
        # 100*0.60 + 100*0.62 + 50*0.64 = 60 + 62 + 32 = 154 -> /250 = 0.616
        self.assertAlmostEqual(fill["average_price"], 0.616, places=6)
        self.assertAlmostEqual(fill["slippage_vs_best"], 0.016, places=6)

    def test_insufficient_depth_reports_unfilled(self):
        book = {"orderbook": {"no": [[40, 50]]}}
        fill = walk_book(book, "YES", 200)
        self.assertFalse(fill["depth_sufficient"])
        self.assertAlmostEqual(fill["filled_contracts"], 50, places=6)
        self.assertAlmostEqual(fill["unfilled_contracts"], 150, places=6)

    def test_empty_book(self):
        self.assertEqual(ask_levels({}, "YES"), [])
        fill = walk_book({}, "YES", 10)
        self.assertFalse(fill["depth_sufficient"])
        self.assertIsNone(fill["average_price"])

    def test_book_depth_dollars(self):
        book = {"orderbook": {"no": [[40, 100], [38, 100]]}}
        # 100*0.60 + 100*0.62 = 122
        self.assertAlmostEqual(book_depth_dollars(book, "YES"), 122.0, places=6)


class TestExecutionQuoting(unittest.TestCase):

    def test_yes_pays_the_ask(self):
        m = market(bid=0.58, ask=0.62)
        ok, flags, details = check_market_executable(m, leg(), 10, "YES")
        self.assertTrue(ok)
        self.assertAlmostEqual(details["exec_price"], 0.62, places=6)

    def test_no_pays_one_minus_bid(self):
        m = market(bid=0.58, ask=0.62)
        ok, flags, details = check_market_executable(m, leg(side="NO"), 10, "NO")
        self.assertTrue(ok)
        self.assertAlmostEqual(details["exec_price"], 0.42, places=6)

    def test_reject_when_market_missing(self):
        ok, flags, details = check_market_executable({}, leg(), 10, "YES")
        self.assertFalse(ok)
        self.assertEqual(flags[0]["flag_type"], "MISSING_DATA")

    def test_reject_closed_market(self):
        ok, flags, details = check_market_executable(market(status="closed"), leg(), 10, "YES")
        self.assertFalse(ok)
        self.assertEqual(flags[0]["flag_type"], "IMPOSSIBLE_EXECUTION")

    def test_reject_settled_market(self):
        ok, _, _ = check_market_executable(market(status="settled"), leg(), 10, "YES")
        self.assertFalse(ok)

    def test_zero_quantity_rejected(self):
        ok, flags, _ = check_market_executable(market(), leg(quantity=0), 0, "YES")
        self.assertFalse(ok)

    def test_oversized_order_rejected(self):
        """A position >50% of traded liquidity is not executable."""
        m = market(volume=100, liquidity=100)
        ok, flags, details = check_market_executable(m, leg(price=0.60), 1000, "YES")
        self.assertFalse(ok)
        self.assertTrue(any(f["flag_type"] == "IMPOSSIBLE_EXECUTION" for f in flags))

    def test_moderately_large_order_flagged_not_rejected(self):
        m = market(volume=1000, liquidity=1000)
        ok, flags, details = check_market_executable(m, leg(price=0.60), 300, "YES")
        self.assertTrue(ok)
        self.assertTrue(any(f["flag_type"] == "LIQUIDITY_PROBLEM" for f in flags))

    def test_missing_book_is_flagged_not_invented(self):
        ok, flags, details = check_market_executable(market(), leg(), 10, "YES")
        self.assertTrue(ok)
        self.assertFalse(details["depth_modelled"])
        self.assertTrue(any(f["flag_type"] == "ORDERBOOK_MISSING" for f in flags))

    def test_missing_quote_falls_back_to_last_and_flags(self):
        m = market(bid=None, ask=None, last=0.55)
        ok, flags, details = check_market_executable(m, leg(), 10, "YES")
        self.assertTrue(ok)
        self.assertAlmostEqual(details["exec_price"], 0.55, places=6)
        self.assertTrue(any(f["flag_type"] == "ORDERBOOK_MISSING" for f in flags))


class TestOrderBookExecution(unittest.TestCase):

    def test_book_drives_execution_price(self):
        m = market(bid=0.58, ask=0.60)
        book = {"book": {"orderbook": {"no": [[40, 100], [38, 100]]}}}
        trade = {"trade_id": "t1", "user_id": "u1", "username": "t", "strategy_id": "S",
                 "status": "ORDER", "legs": [leg(quantity=150)], "position_size_dollars": 0.0,
                 "flags": [], "official_sources": []}
        executed = simulate_execution(trade, {m["ticker"]: m}, {m["ticker"]: book})
        self.assertEqual(executed["status"], "EXECUTED")
        # 100 @ 0.60 + 50 @ 0.62 = 91.00
        self.assertAlmostEqual(executed["position_size_dollars"], 91.00, places=2)

    def test_partial_depth_shrinks_the_fill(self):
        m = market(bid=0.58, ask=0.60, volume=100000, liquidity=100000)
        book = {"book": {"orderbook": {"no": [[40, 50]]}}}
        trade = {"trade_id": "t2", "user_id": "u1", "username": "t", "strategy_id": "S",
                 "status": "ORDER", "legs": [leg(quantity=200)], "position_size_dollars": 0.0,
                 "flags": [], "official_sources": []}
        executed = simulate_execution(trade, {m["ticker"]: m}, {m["ticker"]: book})
        self.assertEqual(executed["status"], "EXECUTED")
        self.assertEqual(executed["legs"][0]["quantity"], 50)
        self.assertEqual(executed["legs"][0]["quantity_requested"], 200)
        self.assertAlmostEqual(executed["position_size_dollars"], 30.00, places=2)
        self.assertTrue(any(f["flag_type"] == "LIQUIDITY_PROBLEM" for f in executed["flags"]))

    def test_no_double_counted_slippage_without_a_book(self):
        """With no book the fill is at top of book; slippage is 0, not invented."""
        m = market(bid=0.58, ask=0.60)
        trade = {"trade_id": "t3", "user_id": "u1", "username": "t", "strategy_id": "S",
                 "status": "ORDER", "legs": [leg(quantity=100)], "position_size_dollars": 0.0,
                 "flags": [], "official_sources": []}
        executed = simulate_execution(trade, {m["ticker"]: m})
        self.assertEqual(executed["status"], "EXECUTED")
        self.assertAlmostEqual(executed["slippage_assumed"], 0.0, places=6)


class TestExecutionBasics(unittest.TestCase):

    def test_execute_single_leg(self):
        m = market()
        trade = {"trade_id": "t", "user_id": "u", "username": "t", "strategy_id": "S",
                 "status": "ORDER", "legs": [leg(quantity=10)], "position_size_dollars": 0.0,
                 "flags": [], "official_sources": []}
        result = simulate_execution(trade, {m["ticker"]: m})
        self.assertEqual(result["status"], "EXECUTED")
        self.assertEqual(result["result"], "PENDING")

    def test_reject_when_any_leg_is_not_executable(self):
        good = market("GOOD")
        bad = market("BAD", status="closed")
        trade = {"trade_id": "t", "user_id": "u", "username": "t", "strategy_id": "S",
                 "status": "ORDER",
                 "legs": [leg("GOOD", quantity=10), leg("BAD", quantity=10)],
                 "position_size_dollars": 0.0, "flags": [], "official_sources": []}
        result = simulate_execution(trade, {"GOOD": good, "BAD": bad})
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["result"], "REJECTED")

    def test_no_legs_is_rejected(self):
        trade = {"trade_id": "t", "legs": [], "flags": []}
        result = simulate_execution(trade, {})
        self.assertEqual(result["status"], "REJECTED")

    def test_close_sells_at_the_bid(self):
        m = market(bid=0.70, ask=0.72)
        trade = {"trade_id": "t", "user_id": "u", "username": "t", "strategy_id": "S",
                 "status": "EXECUTED", "legs": [leg(quantity=100)],
                 "entry_price_combined": 0.60, "position_size_dollars": 60.0,
                 "fees": 1.68, "contracts": 100, "flags": [], "official_sources": []}
        closed = simulate_close(trade, {m["ticker"]: m})
        self.assertEqual(closed["status"], "CLOSED")
        self.assertAlmostEqual(closed["exit_price_combined"], 0.70, places=6)
        # proceeds 70 - cost 60 - entry fee 1.68 - exit fee ceil(.07*100*.7*.3)=1.47
        self.assertAlmostEqual(closed["pnl_dollars"], 70 - 60 - 1.68 - 1.47, places=2)


if __name__ == "__main__":
    unittest.main()
