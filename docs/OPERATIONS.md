# Operations

## Data Collection

- Workflow: .github/workflows/collect.yml
- Schedule: 12 6,12,18 * * * UTC + extra 42 22 * * 4,6,7,1 (Thu/Sat/Sun/Mon NFL windows)
- Modes: universe, events, candles, live, nfl, weather, full
- Command: python3 scripts/collect.py --mode full
- Output: data/raw/kalshi/universe.json, events/, markets/, candles/, orderbooks/, trades/, runs/, manifest.jsonl
- Verification: python3 scripts/check_manifest.py

## Competition Cycle

- Workflow: .github/workflows/simulate.yml
- Schedule: 22 6,12,18 * * * UTC + 52 22 * * 4,6,7,1 (after collection)
- Command: python3 scripts/simulate.py --users 100
- Steps:
  1. Load shared market data (once)
  2. Evaluate each strategy (lightweight)
  3. Simulate execution (bid/ask, liquidity, 10% depth rule, slippage, fees)
  4. Append to hash-chained ledger (data/competition/ledger.jsonl)
  5. Settle trades where results available
  6. Update user bankrolls, ranks, performance history
  7. Save users.json
- Verification: python3 scripts/verify.py + python3 -m unittest discover -s tests -v
- Site build: python3 scripts/build_site.py (site_data/ + docs/site_data + docs/index.html)

## Pages Deployment

- Workflow: .github/workflows/pages.yml
- Trigger: push to main with docs/** or site_data/** changes
- Serves docs/ folder via GitHub Pages
- Site: https://buffedlizard55-lab.github.io/NFLPARLAYCOMP/

## Scalability Testing

Measured on the offline synthetic fixture (one cycle creating trades, one settling):

| Users | Cycle 1 (create) | Cycle 2 (settle) | Trades created |
| --- | --- | --- | --- |
| 5 | 0.01s | 0.01s | 1 |
| 10 | 0.01s | 0.01s | 6 |
| 15 | 0.01s | 0.01s | 9 |
| 25 | 0.01s | 0.01s | 16 |
| 30 | 0.01s | 0.01s | 19 |
| 50 | 0.01s | 0.01s | 27 |
| 70 | 0.02s | 0.02s | 40 |
| 100 | 0.02s | 0.03s | 56 |
| 250 | 0.05s | 0.06s | 138 |
| 500 | 0.15s | 0.13s | 272 |
| 750 | 0.15s | 0.26s | 406 |
| 1,000 | 0.20s | 0.23s | 541 |

Site output at 1,000 users: ~6.8 MB across ~1,050 files. The largest bundle is
`docs/site_data/trades/index.json` at ~2 MB.

Architecture supports 1,000+ without redesign:
- Shared market data loaded once per cycle (not duplicated per user)
- Ledger tail cached in memory so appends are O(1)
- One shared trade index filtered by `user_id` in the browser (no per-user copies)
- Strategy explanations served once, not per user
- Bounded bundles with pagination; per-view trade lists capped at 200
- Verification flags aggregated by type instead of listed individually

To test 1,000:
```
python3 scripts/simulate.py --users 1000 --clear
python3 scripts/build_site.py
python3 scripts/test_all.py
```

## Paper Trading Realism

- Quotes: buying YES pays the YES ask; buying NO pays `1 - yes_bid`.
  Crossing the spread is already in the price and is NOT charged again as slippage.
- Depth: with an order-book snapshot the order walks real levels
  (`engine/orderbook.py`); `slippage_vs_best` is measured, not assumed.
- No snapshot: fill modelled at top of book and flagged `ORDERBOOK_MISSING`.
- Partial fills: a leg larger than resting depth is partially filled and flagged.
- Liquidity limits: reject above 50% of traded liquidity, flag above 10%.
- Fees: official Kalshi schedule, charged ON EXECUTION per leg —
  `round up(M x 0.07 x C x P x (1-P))`, no settlement fee (`engine/fees.py`).
  A synthetic N-leg parlay pays N fees.
- Market status: only `active`/`open` markets are executable.
- Settlement: official results are read from each settled market's `result` field and
  stamped `OFFICIAL`; when none is stored, the outcome is drawn from the
  market-implied probability and stamped `SIMULATED` with a `SIMULATED_SETTLEMENT`
  flag on the trade.

## Running the gates

```
python3 scripts/test_all.py
```

Runs, in order: the Python unit tests, the ledger + verification audit, the fetch
manifest audit, and (when node is present) the front-end smoke test that executes
`docs/app.js` against the real bundles. Non-zero exit on any failure. This is what
CI runs.

## Verification

- Hash chain: `verify_chain()` recomputes SHA-256(prev_hash + canonical_json(entry))
  for every entry, checks `prev_hash` linkage, and checks `ledger_seq` ordering.
- Manifest: every fetch logged with URL, status, bytes, SHA-256, time.
- Trades: price bounds [0.01,0.99], timestamps, market file existence.
- Reproducibility: every settled trade's stored PnL is re-derived as
  `payout - cost - fees`; a mismatch raises `CALCULATION_ERROR`.
- State: a `CANDIDATE`/`SIGNAL`/`ORDER` record carrying a position size is flagged,
  because a signal must never be treated as an executed trade.
- Users: username, bankroll, rank.
- Full report: `data/competition/verification_report.json`, served (aggregated) at
  `docs/site_data/verification.json`.

## Flags

See docs/FLAGS.md

## No Manual Input

All autonomous via APIs. If external source cannot be automatically verified, flag for review.

## Workflow cron constraint (important)

GitHub's `schedule` cron dialect is **stricter than POSIX**: the day-of-week field
is `0-6` with `0` = Sunday. POSIX also accepts `7` for Sunday — but if a `7` appears
in a workflow's cron, **GitHub rejects the entire workflow file**. The workflow then
cannot run at all, including via `workflow_dispatch`, and the only symptom is a run
that is created and fails in 0 seconds with **no jobs, no logs and no check runs**.
That looks like a permissions or policy problem rather than a typo, which is why it
went unnoticed here: both scheduled workflows were non-functional while appearing
perfectly valid to standard cron tools and YAML parsers.

`tests/test_workflows.py` now validates every cron entry against GitHub's dialect,
so this class of failure is caught by `scripts/test_all.py` instead of in the
Actions tab.

## Bundle layout

Site bundles are written **only** to `docs/site_data/`, because GitHub Pages serves
`docs/`. A second copy at the repository root was removed: it committed every byte
twice, and `tests/test_site.py` fails if it reappears.

## Limitations

- Kalshi API may be blocked in the sandbox; synthetic fixtures are used, flagged
  UNVERIFIED, purely for offline testing. Real collection runs in GitHub Actions.
- Historical weather is unavailable from NWS (forward-only), so weather strategies
  are forward-only by construction.
- The public trade tape only covers the last few hours; candlesticks are the
  historical price source.
- Combo markets are rare and RFQ-priced, so parlays are modelled as synthetic
  portfolios with a `SYNTHETIC_PARLAY` flag rather than as native combos.
- More real collection cycles are needed to populate a full 2026 season.
