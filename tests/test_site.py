"""Site-build tests.

The GitHub Pages site is static, so a broken bundle or a syntax error in app.js is
only visible in a browser. These tests build the site into a scratch directory and
assert the contract the pages rely on:

  * every JSON bundle the JS fetches actually exists and is valid JSON
  * app.js parses (via `node --check` when node is available)
  * the site distinguishes real verified data from simulated activity
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
# Bundles are written directly into docs/ because that is what GitHub Pages serves;
# keeping a second copy at the repository root would double the committed bytes.
SITE_DATA = os.path.join(DOCS, "site_data")


class TestSiteBundles(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from engine import site_builder
        site_builder.main()

    def test_required_bundles_exist_and_parse(self):
        required = [
            "competition.json", "leaderboard.json", "strategies.json",
            "verification.json", "data_sources.json", "markets.json",
            "trades/recent.json", "trades/upcoming.json", "trades/closed.json",
            "trades/rejected.json", "trades/ledger_summary.json",
        ]
        for rel in required:
            path = os.path.join(SITE_DATA, rel)
            with self.subTest(bundle=rel):
                self.assertTrue(os.path.exists(path), f"missing bundle {rel}")
                with open(path, encoding="utf-8") as handle:
                    json.load(handle)  # must be valid JSON

    def test_assets_are_present_in_docs(self):
        for rel in ("index.html", "style.css", "app.js", ".nojekyll"):
            with self.subTest(asset=rel):
                self.assertTrue(os.path.exists(os.path.join(DOCS, rel)),
                                f"missing docs asset {rel}")
        # The site fetches from ./site_data, which must exist under docs/.
        self.assertTrue(os.path.isdir(os.path.join(DOCS, "site_data")))

    def test_no_duplicate_bundle_at_repository_root(self):
        """Guards against re-introducing a second copy of every bundle."""
        self.assertFalse(os.path.isdir(os.path.join(ROOT, "site_data")),
                         "root site_data/ duplicates docs/site_data/; see engine/site_builder.py")

    def test_app_js_has_valid_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available to parse app.js")
        result = subprocess.run([node, "--check", os.path.join(DOCS, "app.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         f"app.js failed to parse:\n{result.stderr}")

    def test_app_js_only_fetches_paths_that_exist(self):
        """Catch a renamed bundle leaving a dead fetch behind."""
        with open(os.path.join(DOCS, "app.js"), encoding="utf-8") as handle:
            js = handle.read()
        import re
        # site_data/... literals, ignoring template placeholders we resolve below.
        paths = set(re.findall(r"site_data/[A-Za-z0-9_./\-]+\.json", js))
        for rel in paths:
            with self.subTest(path=rel):
                self.assertTrue(os.path.exists(os.path.join(DOCS, rel)),
                                f"app.js fetches {rel} but docs/{rel} does not exist")

    def test_leaderboard_pagination_covers_all_users(self):
        with open(os.path.join(SITE_DATA, "leaderboard.json"), encoding="utf-8") as handle:
            full = json.load(handle)
        total = full["count"]
        page_size = 25
        collected = []
        page = 1
        while True:
            path = os.path.join(SITE_DATA, f"leaderboard_page_{page}.json")
            if not os.path.exists(path):
                break
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            collected.extend(payload["users"])
            page += 1
        self.assertEqual(len(collected), total,
                         "paginated leaderboard pages must cover every user exactly once")
        self.assertLessEqual(max(len(p["users"]) for p in
                                 [json.load(open(os.path.join(SITE_DATA, f"leaderboard_page_{i}.json")))
                                  for i in range(1, page)]), page_size)

    def test_every_user_has_a_profile_bundle(self):
        with open(os.path.join(SITE_DATA, "leaderboard.json"), encoding="utf-8") as handle:
            users = json.load(handle)["users"]
        missing = [u["user_id"] for u in users
                   if not os.path.exists(os.path.join(SITE_DATA, "users", f"{u['user_id']}.json"))]
        self.assertEqual(missing, [], f"users without a profile bundle: {missing[:5]}")

    def test_verified_data_and_simulated_activity_are_distinguishable(self):
        """The overview must state whether real Kalshi data is present."""
        with open(os.path.join(SITE_DATA, "competition.json"), encoding="utf-8") as handle:
            overview = json.load(handle)
        self.assertIn("data_provenance", overview)
        prov = overview["data_provenance"]
        self.assertIn("real_kalshi_data_present", prov)
        self.assertIsInstance(prov["real_kalshi_data_present"], bool)
        self.assertTrue(prov["note"])
        # Counts must be internally coherent.
        self.assertIn("ledger_entries", overview)
        self.assertGreaterEqual(overview["ledger_entries"], overview["total_trades"])

    def test_settled_trades_carry_provenance(self):
        """Any settled trade shown to a viewer must say where its outcome came from."""
        with open(os.path.join(SITE_DATA, "trades", "closed.json"), encoding="utf-8") as handle:
            closed = json.load(handle)["trades"]
        if not closed:
            self.skipTest("no closed trades in this build")
        untagged = [t["trade_id"] for t in closed if not t.get("settlement_result_source")]
        self.assertEqual(untagged, [],
                         f"settled trades missing settlement provenance: {untagged[:5]}")

    def test_simulated_settlements_are_flagged(self):
        with open(os.path.join(SITE_DATA, "trades", "closed.json"), encoding="utf-8") as handle:
            closed = json.load(handle)["trades"]
        for t in closed:
            if t.get("settlement_result_source") in ("SIMULATED", "PARTIAL"):
                types = {f.get("flag_type") for f in t.get("flags", [])}
                self.assertIn("SIMULATED_SETTLEMENT", types,
                              f"{t['trade_id']} settled by simulation without a flag")

    def test_pnl_is_reproducible_from_stored_fields(self):
        """Every settled trade's PnL must equal payout - cost - fees."""
        with open(os.path.join(SITE_DATA, "trades", "closed.json"), encoding="utf-8") as handle:
            closed = json.load(handle)["trades"]
        checked = 0
        for t in closed:
            if t.get("pnl_dollars") is None or t.get("payout_dollars") is None:
                continue
            expected = t["payout_dollars"] - t["position_size_dollars"] - (t.get("fees") or 0)
            with self.subTest(trade=t["trade_id"]):
                self.assertAlmostEqual(t["pnl_dollars"], expected, places=2)
            checked += 1
        if not checked:
            self.skipTest("no settled trades with full cash-flow fields")

    def test_pages_do_not_embed_all_users_in_one_list(self):
        """Guards against a 1,000-user page becoming one enormous table."""
        with open(os.path.join(DOCS, "index.html"), encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("pageSize", html)
        self.assertIn("pagination", html)
        with open(os.path.join(SITE_DATA, "leaderboard_page_1.json"), encoding="utf-8") as handle:
            page1 = json.load(handle)
        self.assertLessEqual(len(page1["users"]), 25)


if __name__ == "__main__":
    unittest.main()
