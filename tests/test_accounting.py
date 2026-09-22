"""End-to-end accounting tests.

Verifies the money math a reader would manually check:
    Leaderboard -> User -> Trade -> Official Source

Cash-flow model (documented in docs/DATA_TRUTH.md):

    at execution   : bankroll -= (cost + entry_fees)      [cost = price x contracts]
    at settlement  : bankroll += payout                   [$1 per contract if all legs win]
    realised PnL   : payout - cost - entry_fees

Fees come from Kalshi's official schedule and are charged ON EXECUTION, win or lose:
    fees = round up(M x 0.07 x C x P x (1-P))      https://kalshi.com/docs/kalshi-fee-schedule.pdf
There is no settlement fee.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.execution import simulate_execution, simulate_settlement
from engine.parlay import settle_parlay
from engine.fees import kalshi_fee


def make_market(ticker="KXNFLGAME-26SEP20CLETB-TB", bid=0.58, ask=0.60, volume=50000):
    return {
        "ticker": ticker,
        "event_ticker": "KXNFLGAME-26SEP20CLETB",
        "series_ticker": "KXNFLGAME",
        "status": "active",
        "yes_bid": bid,
        "yes_ask": ask,
        "last_price": (bid + ask) / 2,
        "volume": volume,
        "liquidity": volume,
    }


def make_trade(quantity=100, side="YES", ticker="KXNFLGAME-26SEP20CLETB-TB"):
    return {
        "trade_id": "t1",
        "user_id": "u1",
        "username": "tester",
        "strategy_id": "STRAT_TEST",
        "status": "ORDER",
        "legs": [{
            "market_ticker": ticker,
            "event_ticker": "KXNFLGAME-26SEP20CLETB",
            "series_ticker": "KXNFLGAME",
            "side": side,
            "entry_price": 0.60,
            "quantity": quantity,
        }],
        "position_size_dollars": 0.0,
        "flags": [],
        "official_sources": [],
    }


class TestAccounting(unittest.TestCase):

    def test_execution_price_and_cost(self):
        market = make_market()
        executed = simulate_execution(make_trade(quantity=100), {market["ticker"]: market})
        self.assertEqual(executed["status"], "EXECUTED")
        # 100 contracts bought at the YES ask of $0.60
        self.assertAlmostEqual(executed["position_size_dollars"], 60.00, places=4)
        self.assertAlmostEqual(executed["entry_price_combined"], 0.60, places=6)
        # Fee: ceil(0.07 x 100 x 0.60 x 0.40) = ceil(1.68) = 1.68
        self.assertAlmostEqual(executed["fees"], 1.68, places=2)
        self.assertAlmostEqual(executed["total_debit_dollars"], 61.68, places=2)

    def test_win_settlement_cash_flows(self):
        bankroll = 10000.0
        market = make_market()
        executed = simulate_execution(make_trade(quantity=100), {market["ticker"]: market})
        bankroll -= executed["total_debit_dollars"]
        self.assertAlmostEqual(bankroll, 9938.32, places=2)

        settled = simulate_settlement(executed, {market["ticker"]: "yes"})
        self.assertEqual(settled["status"], "SETTLED")
        self.assertEqual(settled["result"], "WIN")
        # payout 100 x $1 = $100 ; cost $60 ; fee $1.68  ->  pnl $38.32
        self.assertAlmostEqual(settled["payout_dollars"], 100.00, places=2)
        self.assertAlmostEqual(settled["pnl_dollars"], 38.32, places=2)

        bankroll += settled["payout_dollars"]
        self.assertAlmostEqual(bankroll, 10038.32, places=2)
        # The bankroll delta equals the recorded PnL, exactly.
        self.assertAlmostEqual(bankroll, 10000.0 + settled["pnl_dollars"], places=2)

    def test_loss_settlement_cash_flows(self):
        bankroll = 10000.0
        market = make_market()
        executed = simulate_execution(make_trade(quantity=100), {market["ticker"]: market})
        bankroll -= executed["total_debit_dollars"]

        settled = simulate_settlement(executed, {market["ticker"]: "no"})
        self.assertEqual(settled["result"], "LOSS")
        # A loser receives nothing and loses the stake PLUS the fee already paid.
        self.assertAlmostEqual(settled["payout_dollars"], 0.0, places=4)
        self.assertAlmostEqual(settled["pnl_dollars"], -61.68, places=2)

        bankroll += settled["payout_dollars"]
        self.assertAlmostEqual(bankroll, 9938.32, places=2)
        self.assertAlmostEqual(bankroll, 10000.0 + settled["pnl_dollars"], places=2)

    def test_settlement_is_fee_free(self):
        """The schedule states: 'There is no settlement fee.'"""
        market = make_market()
        executed = simulate_execution(make_trade(quantity=100), {market["ticker"]: market})
        settled = simulate_settlement(executed, {market["ticker"]: "yes"})
        # Entry fee is carried forward unchanged; nothing is added at settlement.
        self.assertAlmostEqual(settled["fees"], executed["fees"], places=6)

    def test_settlement_passes_cash_flow_fields(self):
        """Regression: the runner needs payout back to credit the bankroll.

        Without it the stake was never returned on a win (winners bled money) and
        losing trades silently over-credited the bankroll by their own cost.
        """
        market = make_market()
        executed = simulate_execution(make_trade(quantity=100), {market["ticker"]: market})
        settled = simulate_settlement(executed, {market["ticker"]: "yes"})
        for field in ("position_size_dollars", "fees", "payout_dollars", "cash_out_dollars"):
            self.assertIn(field, settled)
        self.assertAlmostEqual(settled["position_size_dollars"],
                               executed["position_size_dollars"], places=4)
        self.assertAlmostEqual(settled["cash_out_dollars"],
                               settled["position_size_dollars"] + settled["fees"], places=4)

    def test_no_side_uses_complementary_price(self):
        """Buying NO pays 1 - yes_bid, not the YES ask."""
        market = make_market(bid=0.58, ask=0.60)
        executed = simulate_execution(make_trade(quantity=100, side="NO"),
                                      {market["ticker"]: market})
        self.assertAlmostEqual(executed["entry_price_combined"], 0.42, places=6)
        self.assertAlmostEqual(executed["position_size_dollars"], 42.00, places=2)
        # Fee on the NO leg is charged at the NO price: ceil(0.07*100*0.42*0.58) = 1.71
        self.assertAlmostEqual(executed["fees"], kalshi_fee(0.42, 100), places=6)

    def test_no_side_wins_when_market_resolves_no(self):
        market = make_market(bid=0.58, ask=0.60)
        executed = simulate_execution(make_trade(quantity=100, side="NO"),
                                      {market["ticker"]: market})
        settled = simulate_settlement(executed, {market["ticker"]: "no"})
        self.assertEqual(settled["result"], "WIN")
        # payout 100 - cost 42 - fee 1.71 = 56.29
        self.assertAlmostEqual(settled["pnl_dollars"], 56.29, places=2)

    def test_parlay_win_requires_every_leg(self):
        legs = [
            {"market_ticker": "A", "side": "YES", "entry_price": 0.60},
            {"market_ticker": "B", "side": "YES", "entry_price": 0.50},
        ]
        trade = {"legs": legs, "entry_price_combined": 0.30, "position_size_dollars": 30.0,
                 "fees": 0.0}
        # One leg fails -> whole parlay loses the stake
        loss = settle_parlay(trade, {"A": "yes", "B": "no"})
        self.assertEqual(loss["result"], "LOSS")
        self.assertAlmostEqual(loss["payout_dollars"], 0.0, places=4)
        self.assertAlmostEqual(loss["pnl_dollars"], -30.0, places=4)
        # Both legs land -> parlay pays $1 per contract (100 contracts held)
        win = settle_parlay(trade, {"A": "yes", "B": "yes"})
        self.assertEqual(win["result"], "WIN")
        self.assertAlmostEqual(win["contracts"], 100.0, places=6)
        self.assertAlmostEqual(win["payout_dollars"], 100.0, places=4)
        self.assertAlmostEqual(win["pnl_dollars"], 70.0, places=4)

    def test_parlay_pays_fee_per_leg(self):
        """A synthetic parlay is N separate orders, so it pays N fees."""
        legs = [
            {"market_ticker": "A", "entry_price": 0.60, "quantity": 100,
             "series_ticker": "KXNFLGAME"},
            {"market_ticker": "B", "entry_price": 0.50, "quantity": 100,
             "series_ticker": "KXNFLSPREAD"},
        ]
        trade = {
            "trade_id": "p1", "user_id": "u1", "username": "t", "strategy_id": "S",
            "status": "ORDER", "legs": legs, "position_size_dollars": 0.0,
            "flags": [], "official_sources": [],
        }
        markets = {
            "A": make_market("A", 0.58, 0.60),
            "B": make_market("B", 0.48, 0.50),
        }
        executed = simulate_execution(trade, markets)
        self.assertEqual(executed["status"], "EXECUTED")
        expected = kalshi_fee(0.60, 100) + kalshi_fee(0.50, 100)
        self.assertAlmostEqual(executed["fees"], expected, places=2)
        self.assertAlmostEqual(executed["fees"], 1.68 + 1.75, places=2)

    def test_total_fees_reduce_pnl_exactly(self):
        market = make_market()
        executed = simulate_execution(make_trade(quantity=100), {market["ticker"]: market})
        settled = simulate_settlement(executed, {market["ticker"]: "yes"})
        gross = settled["payout_dollars"] - settled["position_size_dollars"]
        self.assertAlmostEqual(settled["pnl_dollars"], gross - settled["fees"], places=4)

    def test_missing_leg_result_stays_pending(self):
        trade = {"legs": [{"market_ticker": "A", "side": "YES", "entry_price": 0.6}],
                 "entry_price_combined": 0.6, "position_size_dollars": 60.0, "fees": 0.0}
        result = settle_parlay(trade, {})
        self.assertEqual(result["status"], "PENDING")

    def test_roi_is_pnl_over_cost(self):
        market = make_market()
        executed = simulate_execution(make_trade(quantity=100), {market["ticker"]: market})
        settled = simulate_settlement(executed, {market["ticker"]: "yes"})
        expected_roi = settled["pnl_dollars"] / settled["position_size_dollars"] * 100
        self.assertAlmostEqual(settled["roi_percent"], round(expected_roi, 2), places=2)


if __name__ == "__main__":
    unittest.main()
