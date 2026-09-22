import unittest, os, sys, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.ledger import compute_hash, verify_chain, append_trade, read_ledger, clear_ledger

class TestLedger(unittest.TestCase):
    def setUp(self):
        # Use temp dir for ledger
        import engine.ledger as ledger_mod
        self.orig_path = ledger_mod.LEDGER_PATH
        self.orig_dir = ledger_mod.TRADES_DIR
        self.tmpdir = tempfile.mkdtemp()
        ledger_mod.LEDGER_PATH = os.path.join(self.tmpdir, "ledger.jsonl")
        ledger_mod.TRADES_DIR = os.path.join(self.tmpdir, "trades")
        os.makedirs(ledger_mod.TRADES_DIR, exist_ok=True)

    def tearDown(self):
        import engine.ledger as ledger_mod
        ledger_mod.LEDGER_PATH = self.orig_path
        ledger_mod.TRADES_DIR = self.orig_dir
        shutil.rmtree(self.tmpdir)

    def test_hash_chain(self):
        trade1 = {"trade_id": "t1", "user_id": "u1", "legs": []}
        trade2 = {"trade_id": "t2", "user_id": "u1", "legs": []}
        append_trade(trade1)
        append_trade(trade2)
        result = verify_chain()
        self.assertTrue(result["valid"])
        self.assertEqual(result["count"], 2)

    def test_tamper_detection(self):
        trade1 = {"trade_id": "t1", "user_id": "u1", "legs": []}
        appended = append_trade(trade1)
        # Tamper file
        import engine.ledger as ledger_mod
        with open(ledger_mod.LEDGER_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        tampered = json.loads(lines[0])
        tampered["user_id"] = "hacker"
        with open(ledger_mod.LEDGER_PATH, "w", encoding="utf-8") as f:
            f.write(json.dumps(tampered) + "\n")
        result = verify_chain()
        self.assertFalse(result["valid"])

if __name__ == "__main__":
    unittest.main()
