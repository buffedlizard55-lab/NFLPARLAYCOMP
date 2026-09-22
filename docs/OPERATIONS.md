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

Tested scaling:
- 5 users: 4 trades, 1 settled
- 10 users: 5 trades, 1 settled
- 100 users: 22 trades, 6 settled
- 250 users: 72 trades, 33 settled
- 500 users: 122 trades, 74 settled
- 1000 users: 237 trades, 177 settled (verified chain valid)

Architecture supports 1000+ without redesign:
- Shared market data (not duplicated per user)
- Lightweight users.json
- Hash-chained ledger.jsonl (append-only)
- Pre-aggregated site_data JSON with pagination

To test 1000:
```
python3 scripts/simulate.py --users 1000 --clear
python3 scripts/build_site.py
```

## Paper Trading Realism

- Bid/ask: use yes_bid/yes_ask if available, else last_price
- Liquidity: reject if position >50% liquidity, flag if >10%
- Spread: flag if >10c, slippage bps = spread*0.5
- Slippage: default 10 bps, max 100 bps
- Fees: 7% of profit (Kalshi documented)
- Market status: only active/open executable
- Orderbook: when available from live snapshots
- Settlement: from settled markets, else simulated for testing

## Verification

- Hash chain: verify_chain() recomputes SHA-256(prev_hash + canonical_json(trade))
- Manifest: every fetch logged with URL, status, bytes, SHA-256, time
- Trades: price bounds [0.01,0.99], timestamps, market file existence, PnL calc
- Users: username, bankroll, rank
- Full report: data/competition/verification_report.json + site_data/verification.json

## Flags

See docs/FLAGS.md

## No Manual Input

All autonomous via APIs. If external source cannot be automatically verified, flag for review.

## Limitations

- Kalshi API may be blocked in sandbox, synthetic fixtures used flagged as UNVERIFIED for offline testing. Real collection works in GitHub Actions.
- Historical weather unavailable from NWS (forward-only)
- Trade tape only recent few hours, candles used for historical
- Combo markets rare, RFQ pricing, synthetic model used with flags
- Need more real data collection cycles for full 2026 season
