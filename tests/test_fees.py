"""Fee-model tests.

Every expected value below is transcribed from the "General Trading Fees Table" in
Kalshi's official fee schedule (effective July 7, 2026):
    https://kalshi.com/docs/kalshi-fee-schedule.pdf

If Kalshi republishes the schedule and these fail, the CODE may be right and the
table new — re-verify against the PDF before changing either.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.fees import (kalshi_fee, kalshi_fee_raw, kalshi_fee_precise,
                         series_multiplier, entry_fees, TAKER_RATE, MAKER_RATE)


class TestOfficialFeeTable(unittest.TestCase):
    """Published fee for 100 contracts, by contract price."""

    # (price, published fee for 100 contracts)
    PUBLISHED = [
        (0.01, 0.07), (0.05, 0.34), (0.10, 0.63), (0.15, 0.90), (0.20, 1.12),
        (0.25, 1.32), (0.30, 1.47), (0.35, 1.60), (0.40, 1.68), (0.45, 1.74),
        (0.50, 1.75), (0.55, 1.74), (0.60, 1.68), (0.65, 1.60), (0.70, 1.47),
        (0.75, 1.32), (0.80, 1.12), (0.85, 0.90), (0.90, 0.63), (0.95, 0.34),
        (0.99, 0.07),
    ]

    def test_matches_published_table(self):
        for price, expected in self.PUBLISHED:
            with self.subTest(price=price):
                self.assertAlmostEqual(kalshi_fee(price, 100), expected, places=2)

    def test_fee_is_symmetric_around_fifty_cents(self):
        self.assertAlmostEqual(kalshi_fee(0.30, 100), kalshi_fee(0.70, 100), places=6)
        self.assertAlmostEqual(kalshi_fee(0.20, 100), kalshi_fee(0.80, 100), places=6)

    def test_fee_peaks_at_fifty_cents(self):
        fees = [kalshi_fee(p / 100, 100) for p in range(1, 100)]
        self.assertAlmostEqual(max(fees), 1.75, places=2)

    def test_rounds_up_not_to_nearest(self):
        # 0.07 x 100 x 0.45 x 0.55 = 1.7325 -> published fee is 1.74 (rounded up)
        self.assertAlmostEqual(kalshi_fee_raw(0.45, 100), 1.7325, places=6)
        self.assertAlmostEqual(kalshi_fee(0.45, 100), 1.74, places=6)

    def test_no_fee_on_zero_or_negative_quantity(self):
        self.assertEqual(kalshi_fee(0.50, 0), 0.0)
        self.assertEqual(kalshi_fee(0.50, -5), 0.0)


class TestMultipliers(unittest.TestCase):

    def test_nfl_game_multiplier_is_one(self):
        # Schedule: KXNFLGAME "Professional Football Game" -> Maker 1, Taker 1
        self.assertEqual(series_multiplier("KXNFLGAME"), 1.0)
        self.assertEqual(series_multiplier("KXNFLGAME", maker=True), 1.0)

    def test_combo_multiplier(self):
        # Schedule: "Combos (excluding uncorrelated NFL Championship combos)" -> Maker 2, Taker 1
        self.assertEqual(series_multiplier("KXNFLCOMBO"), 1.0)          # taker
        self.assertEqual(series_multiplier("KXNFLCOMBO", maker=True), 2.0)

    def test_unknown_series_defaults_to_one(self):
        self.assertEqual(series_multiplier("KXNFLSPREAD"), 1.0)
        self.assertEqual(series_multiplier(None), 1.0)

    def test_maker_fee_is_quarter_of_taker(self):
        self.assertAlmostEqual(MAKER_RATE / TAKER_RATE, 0.25, places=6)
        taker = kalshi_fee(0.50, 100, maker=False)
        maker = kalshi_fee(0.50, 100, maker=True)
        self.assertAlmostEqual(maker, 0.44, places=2)   # ceil(0.0175*100*0.25) = ceil(0.4375)
        self.assertGreater(taker, maker)


class TestParlayFees(unittest.TestCase):

    def test_each_leg_charged_separately(self):
        legs = [
            {"exec_price": 0.60, "quantity": 100, "series_ticker": "KXNFLGAME"},
            {"exec_price": 0.50, "quantity": 100, "series_ticker": "KXNFLSPREAD"},
        ]
        total = entry_fees(legs)
        self.assertAlmostEqual(total, 1.68 + 1.75, places=2)

    def test_single_leg(self):
        legs = [{"exec_price": 0.45, "quantity": 100, "series_ticker": "KXNFLGAME"}]
        self.assertAlmostEqual(entry_fees(legs), 1.74, places=2)

    def test_legs_without_quantity_are_skipped(self):
        legs = [{"exec_price": 0.60, "quantity": 0}, {"entry_price": 0.60}]
        self.assertEqual(entry_fees(legs), 0.0)

    def test_small_parlay_fee_is_small(self):
        """10 contracts at 60c: ceil(0.07*10*0.6*0.4) = ceil(0.168) = 0.17"""
        legs = [{"exec_price": 0.60, "quantity": 10}]
        self.assertAlmostEqual(entry_fees(legs), 0.17, places=6)


class TestPrecision(unittest.TestCase):

    def test_precise_rounding_is_finer_than_cent(self):
        raw = kalshi_fee_raw(0.45, 100)          # 1.7325
        precise = kalshi_fee_precise(0.45, 100)  # rounded up at 1e-6
        self.assertGreaterEqual(precise, raw)
        self.assertLess(precise - raw, 1e-6)


if __name__ == "__main__":
    unittest.main()
