import unittest, os, sys, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.ledger import (compute_hash, verify_chain, append_trade, read_ledger,
                           clear_ledger, latest_trades, ledger_length)


class TestLedger(unittest.TestCase):
    def setUp(self):
        # Redirect the ledger to a temp dir
        import engine.ledger as ledger_mod
        self.orig_path = ledger_mod.LEDGER_PATH
        self.orig_dir = ledger_mod.TRADES_DIR
        self.orig_tail = ledger_mod._TAIL
        self.tmpdir = tempfile.mkdtemp()
        ledger_mod.LEDGER_PATH = os.path.join(self.tmpdir, "ledger.jsonl")
        ledger_mod.TRADES_DIR = os.path.join(self.tmpdir, "trades")
        ledger_mod._TAIL = None
        os.makedirs(ledger_mod.TRADES_DIR, exist_ok=True)

    def tearDown(self):
        import engine.ledger as ledger_mod
        ledger_mod.LEDGER_PATH = self.orig_path
        ledger_mod.TRADES_DIR = self.orig_dir
        ledger_mod._TAIL = self.orig_tail
        shutil.rmtree(self.tmpdir)

    def test_hash_chain(self):
        trade1 = {"trade_id": "t1", "user_id": "u1", "legs": []}
        trade2 = {"trade_id": "t2", "user_id": "u1", "legs": []}
        append_trade(trade1)
        append_trade(trade2)
        result = verify_chain()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["count"], 2)

    def test_tamper_detection(self):
        append_trade({"trade_id": "t1", "user_id": "u1", "legs": []})
        import engine.ledger as ledger_mod
        with open(ledger_mod.LEDGER_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        tampered = json.loads(lines[0])
        tampered["user_id"] = "hacker"
        with open(ledger_mod.LEDGER_PATH, "w", encoding="utf-8") as f:
            f.write(json.dumps(tampered) + "\n")
        result = verify_chain()
        self.assertFalse(result["valid"])

    def test_many_appends_in_one_process_chain_correctly(self):
        """Regression: the tail cache must advance on every append.

        A missing `global` on the cache made every append after the first reuse
        prev_hash=None, breaking the chain for any multi-trade cycle.
        """
        for i in range(25):
            append_trade({"trade_id": f"t{i}", "user_id": "u1", "legs": [], "status": "SIGNAL"})
        result = verify_chain()
        self.assertTrue(result["valid"], result["errors"][:3])
        self.assertEqual(result["count"], 25)
        rows = read_ledger()
        # Every entry after the first must chain onto its predecessor.
        for prev, cur in zip(rows, rows[1:]):
            self.assertEqual(cur["prev_hash"], prev["hash"])
            self.assertEqual(cur["ledger_seq"], prev["ledger_seq"] + 1)

    def test_state_transitions_collapse_to_latest(self):
        """The ledger keeps all transitions; latest_trades() returns current state."""
        append_trade({"trade_id": "t1", "user_id": "u1", "status": "SIGNAL", "legs": []})
        append_trade({"trade_id": "t1", "user_id": "u1", "status": "ORDER", "legs": []})
        append_trade({"trade_id": "t1", "user_id": "u1", "status": "EXECUTED", "legs": []})
        append_trade({"trade_id": "t2", "user_id": "u1", "status": "SIGNAL", "legs": []})
        self.assertEqual(len(read_ledger()), 4)          # full audit trail
        latest = latest_trades()
        self.assertEqual(len(latest), 2)                  # distinct trades
        by_id = {t["trade_id"]: t for t in latest}
        self.assertEqual(by_id["t1"]["status"], "EXECUTED")
        self.assertEqual(by_id["t2"]["status"], "SIGNAL")

    def test_ledger_length_matches_entries(self):
        for i in range(7):
            append_trade({"trade_id": f"t{i}", "user_id": "u1", "legs": []})
        self.assertEqual(ledger_length(), 7)
        self.assertEqual(len(read_ledger()), 7)

    def test_reopening_process_resumes_chain(self):
        """Simulates a second workflow run: cache reset, chain must continue."""
        append_trade({"trade_id": "t1", "user_id": "u1", "legs": []})
        import engine.ledger as ledger_mod
        ledger_mod._TAIL = None          # fresh process would do this
        append_trade({"trade_id": "t2", "user_id": "u1", "legs": []})
        result = verify_chain()
        self.assertTrue(result["valid"], result["errors"])
        rows = read_ledger()
        self.assertEqual(rows[1]["prev_hash"], rows[0]["hash"])

    def test_clear_resets_chain(self):
        append_trade({"trade_id": "t1", "user_id": "u1", "legs": []})
        clear_ledger()
        self.assertEqual(len(read_ledger()), 0)
        append_trade({"trade_id": "t2", "user_id": "u1", "legs": []})
        rows = read_ledger()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["prev_hash"])
        self.assertEqual(rows[0]["ledger_seq"], 0)


if __name__ == "__main__":
    unittest.main()
