# NFLPARLAYCOMP — NFL Parlay Trading Competition

An auditable **paper-trading competition** for NFL parlay strategies using **real, verified
Kalshi market data**. Many simulated users (target: 1,000+, tested from 5 upward) compete on
NFL parlay-style positions built from real Kalshi NFL contracts. **No real money is ever
traded** — the project contains no order-placement code and no credentials.

## Non-negotiable data rules

* Every price, timestamp, market, contract, liquidity figure, and settlement used by the
  simulation comes from official Kalshi Trade API endpoints (read-only, unauthenticated)
  or from other official/public sources (ESPN keyless APIs, NWS) and is stored verbatim
  with a SHA-256 manifest entry recording the exact request URL and retrieval time.
* Simulated trades are clearly labelled as simulations. Real verified data and simulated
  activity are never blended into one ambiguous field.
* Anything that cannot be verified is **flagged**, never silently estimated.

## Layout

* `engine/` — dependency-free Python package (stdlib only): API client, collector,
  parlay model, strategy library, execution simulator, hash-chained ledger, competition
  runner, verifier, site builder.
* `scripts/` — CLI entry points (`python3 scripts/collect.py`, `scripts/simulate.py`,
  `scripts/verify.py`, `scripts/build_site.py`, ...).
* `data/raw/` — verbatim API snapshots + fetch manifest (shared by all strategies,
  never duplicated per user).
* `data/competition/` — competition state: users, hash-chained trade ledger, candidate
  trades, flags.
* `site_data/` — generated JSON bundles consumed by the static site.
* `docs/` — research notes, market-structure findings, data-truth policy, operations.
* `tests/` — offline unit tests (fixtures only, no network).
* `.github/workflows/` — scheduled data collection + competition cycles on GitHub Actions.

## Quick start

```bash
# run tests (offline)
python3 -m unittest discover -s tests -v

# collect verified data (requires network; runs in GitHub Actions otherwise)
python3 scripts/collect.py --mode full

# run/simulate the competition over collected data
python3 scripts/simulate.py

# audit the ledger and data integrity
python3 scripts/verify.py

# regenerate the static site bundles
python3 scripts/build_site.py
```

The competition website is published at
<https://buffedlizard55-lab.github.io/NFLPARLAYCOMP/>.

## Verification contract

Each simulated trade can be audited via **Leaderboard → User → Trade → Official Source**.
Every trade record carries the market ticker, event ticker, entry/exit timestamps,
prices, quantities, fees, settlement, the exact snapshot files (with SHA-256) the prices
came from, and official links for manual re-verification.

See `docs/DATA_TRUTH.md` for the full evidence policy and `docs/FLAGS.md` for the
flagging system.
