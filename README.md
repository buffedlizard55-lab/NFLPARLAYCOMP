# NFLPARLAYCOMP — NFL Parlay Trading Competition

An auditable **paper-trading competition** in which many simulated users run distinct
NFL strategy programs against **real, verified Kalshi market data**.

**No real money is ever traded.** There is no order-placement code and no credentials
anywhere in this repository. The Kalshi client is read-only and unauthenticated.

Site: https://buffedlizard55-lab.github.io/NFLPARLAYCOMP/

---

## What this project actually is

A simulation engine that:

1. **Collects** real NFL market data from official public endpoints and stores it
   verbatim with a SHA-256 fetch manifest, so every price can be traced back to the
   exact HTTP response it came from.
2. **Runs** dozens of distinct, deterministic NFL strategy programs over that data.
3. **Simulates execution** realistically: quotes, order-book depth, partial fills,
   liquidity limits, official fees, and the market lifecycle from signal to settlement.
4. **Records** every state transition in a hash-chained ledger that can be audited
   for tampering and reconciled by hand.
5. **Publishes** a static site where anyone can go
   **Leaderboard → User → Trade → Official Source** and verify a trade themselves.

The competition is retained as a falsification exercise, not a profit claim. Most
strategies in the library are documented as *unproven hypotheses*; several are
documented as tests whose premise does not match their implementation.

---

## Data rules (non-negotiable)

| Rule | How it is enforced |
| --- | --- |
| Prices come only from the official Kalshi Trade API v2 | `engine/kalshi_client.py` only calls documented endpoints; every response is logged with URL, status, size, SHA-256 and retrieval time |
| NFL metadata comes only from official/public sources | ESPN keyless API (schedule, venues, injuries) and NWS (forecasts) |
| Nothing is invented | Missing data produces a flag and a rejection, never an estimate |
| Real data and simulated activity are never blended | `data_provenance` on the competition bundle; `settlement_result_source` on every settled trade |
| Every important calculation is reproducible | `tests/test_accounting.py` and `engine/verify.py` re-derive PnL from stored fields; `tests/test_site.py` re-derives it from the served bundles |

### Verified third-party facts used

These are the external facts the simulation depends on. Each was read from a primary
source and is asserted by a test, so a source change shows up as a test failure.

| Fact | Source | Test |
| --- | --- | --- |
| Taker fee `round up(M × 0.07 × C × P × (1−P))`, charged at execution; **no settlement fee** | Kalshi Fee Schedule, effective 2026-07-07 — https://kalshi.com/docs/kalshi-fee-schedule.pdf | `tests/test_fees.py` (asserts all 21 published rows) |
| Maker fee `round up(M × 0.0175 × C × P × (1−P))` | same | `tests/test_fees.py` |
| `KXNFLGAME` multiplier = 1; NFL combos maker 2 / taker 1 | same, "Non-Standard Fees" table | `tests/test_fees.py` |
| Order-book payload shape (`orderbook` / `orderbook_fp`) | Kalshi API reference | `tests/test_execution.py` |

### Known-unverified claims

This project deliberately does **not** repeat the strategy-shaped statistics that
circulate in betting communities. Where an earlier draft cited a number (an "edge vs
closing line", a "57% under rate", a "62% fade win rate"), the number has been
**removed** and the strategy now records `Evidence: none established in this
repository`. Several strategies carry an explicit note that their stated premise is
not implemented by their code — those are listed as falsification targets.

---

## What is real and what is simulated

This distinction is the point of the project, so it is stated plainly:

| Layer | Status |
| --- | --- |
| Kalshi markets, tickers, prices, bid/ask, volume, rules, `result` fields | **Real verified data** when `data/raw/kalshi/` is populated by a collection run |
| NFL schedule / venue / injury metadata (ESPN), weather (NWS) | **Real public data** |
| Fee schedule, fee arithmetic | **Real**, transcribed from the official schedule |
| Strategy programs, sizing, model probabilities | **Model output** — explicitly not market data |
| Trades, fills, PnL, bankrolls, rankings | **Simulated (paper trading)** |
| Settlement drawn from market-implied probability when no official result is stored | **Simulated** — stamped `SIMULATED_SETTLEMENT` with a flag on every affected trade |

**Current state of this checkout:** `data/raw/` is empty, so no Kalshi collection has
succeeded here yet. The competition therefore runs on **flagged synthetic fixtures**
(`UNVERIFIED_DATA`) whose only purpose is to exercise and scale-test the machinery.
The site states this at the top of the Overview page via
`data_provenance.real_kalshi_data_present`. No synthetic price is ever presented as a
real quote.

---

## Architecture

```
engine/
  kalshi_client.py   read-only Trade API v2 client + fixture client for tests
  collect.py         verified collector: universe, events, markets, candles, books, tape
  fees.py            Kalshi fee schedule (taker/maker, per-series multipliers)
  orderbook.py       depth model: ask levels, book walking, partial fills
  execution.py       quotes, depth, slippage, liquidity limits, rejections, settlement
  parlay.py          leg validation, synthetic pricing, settlement arithmetic
  strategies.py      37 distinct strategy programs (deterministic, data-driven)
  competition.py     cycle runner: signals -> orders -> fills -> settlement -> ranks
  ledger.py          hash-chained append-only trade ledger (O(1) appends)
  verify.py          audit: chain, manifest, per-trade reproducibility, state checks
  site_builder.py    static site bundles + GitHub Pages assets
  nfl_data.py        NFL metadata loaders
scripts/             collect, simulate, generate_users, verify, build_site,
                     check_manifest, test_all
data/raw/            verbatim API snapshots + fetch manifest (shared, never per-user)
data/competition/    users.json + ledger.jsonl (single source of truth for trades)
docs/                GitHub Pages site; bundles are written to docs/site_data/
tests/               86 unit tests + a Node front-end smoke test
```

### Design decisions that make 1,000+ users cheap

| Decision | Why |
| --- | --- |
| Market data loaded once per cycle, keyed by ticker | 1,000 users share one in-memory dataset instead of holding their own copies |
| Ledger tail cached in memory | Appends are O(1); rescanning per append would be O(n²) per cycle |
| Ledger collapses to latest state via `latest_trades()` | Full audit trail retained without consumers re-reading every transition |
| One shared `trades/index.json`, filtered by `user_id` in the browser | Adding users does not multiply trade storage |
| Strategy explanation served once from `strategies.json` | 37 strategies, not 1,000 copies of the same text |
| Bundles written only to `docs/site_data/` | The served copy is the only copy; a second root-level copy doubled every byte |
| Verification flags aggregated by type | 1,000 users produce thousands of identical flags; the page shows counts plus samples |
| Per-trade sidecar files not written in normal operation | The ledger is authoritative; ~1,000 files per cycle would be pure duplication |

**Measured** (one cycle creating trades, one settling them, on the synthetic fixture):

| Users | Cycle 1 | Cycle 2 | Trades created |
| --- | --- | --- | --- |
| 5 | 0.01s | 0.01s | 1 |
| 50 | 0.01s | 0.01s | 27 |
| 250 | 0.05s | 0.06s | 138 |
| 500 | 0.15s | 0.13s | 272 |
| 1,000 | 0.20s | 0.23s | 541 |

Scaling to 5 → 10 → 15 → 25 → 30 → 50 → 70 → 100 → 250 → 500 → 750 → 1,000 users
requires no architectural change. Site output at 1,000 users: ~6.8 MB across ~1,050
files, of which the shared trade index is the largest single bundle at ~2 MB.

---

## Trade lifecycle

The lifecycle is modeled explicitly and the states are never conflated:

```
CANDIDATE -> SIGNAL -> ORDER -> EXECUTED -> CLOSED
                                       \-> SETTLED
                   \-> CANCELLED
                   \-> REJECTED
```

A `SIGNAL` is **not** an executed trade. Signals and orders carry no position size;
the verifier raises `CALCULATION_ERROR` if one ever does.

### Money math

```
at execution  : bankroll -= (cost + entry fees)     cost = price x contracts
at settlement : bankroll += payout                  payout = $1 per contract if every leg wins
realised PnL  : payout - cost - entry fees
```

Fees are charged **on execution, win or lose** (there is no settlement fee), so a
losing trade still costs its fee. A synthetic N-leg parlay is N separate orders and
therefore pays N fees. `tests/test_accounting.py` checks these identities, and
`engine/verify.py` re-derives every settled trade's PnL from its stored fields at
audit time.

### Execution realism

- Buying YES pays the YES ask; buying NO pays `1 - yes_bid`. Crossing the spread is
  already in the price and is **not** charged again as slippage.
- With a verified order-book snapshot the order **walks real levels**; the recorded
  `slippage_vs_best` is measured, not assumed.
- Without a snapshot, the fill is modelled at top of book and flagged
  `ORDERBOOK_MISSING` — depth is disclosed as unmodelled rather than invented.
- Orders larger than resting depth are **partially filled**; orders above 50% of
  traded liquidity are **rejected** as unexecutable.

---

## Strategy library (37 programs)

Each program documents what information it uses, when it enters, when it avoids,
how it sizes, its expected value, why it might work, why it might fail, and what
evidence supports it. Signals are deterministic functions of stored data —
`tests/test_strategies.py` asserts `strategies.py` contains no randomness at all.

| Category | Count | Examples |
| --- | --- | --- |
| Market-based | 7 | Implied value, line-movement momentum, mean reversion, cross-market, contrarian, liquidity, alt lines |
| Game-based | 7 | Home field, spread+ML correlation, team totals, coaching mismatch |
| Situational | 9 | Weather under, injury fade, indoor over, short week, Q1 under |
| Correlation | 4 | Same-game spread+ML, underdog+under, 1H divergence, TD+win |
| Statistical | 5 | Mean reversion, streak fade, momentum, Elo, DVOA |
| Prop-based | 5 | Anytime TD, first TD, win margin, specials, quarter winner |

**Honesty about the roster:** several strategies are deliberately retained as
falsification targets even though their documented evidence contradicts their
implementation — for example, `STRAT_PRIMETIME_FAVE_015` buys the underdog
*moneyline* while citing a *spread-cover* statistic, and `STRAT_LIQUIDITY_033` models
resting (maker) behaviour but is priced and charged as a taker. Their entries say so.
A library that only contained plausible strategies could not be falsified.

---

## Verification path

Leaderboard → User → Trade → Official Source. For every trade the site exposes:

- market / event / series tickers, side, quantity requested vs filled
- entry price, executed price, exit or settlement price
- bid, ask and quoted spread at entry; liquidity at entry
- entry timestamp, expiration/settlement date, fee model, total debit
- the snapshot file the price came from and its recorded SHA-256
- links to the official Kalshi API endpoint and market page
- the full flag list for that trade
- settlement provenance (`OFFICIAL` vs `SIMULATED`) with a per-leg breakdown
- a re-derivation of the arithmetic: `payout − cost − fees = PnL`

---

## Running it

```bash
# everything: unit tests, ledger/manifest audits, front-end smoke test
python3 scripts/test_all.py

# collect verified data (network required; runs in GitHub Actions otherwise)
python3 scripts/collect.py --mode full

# run the competition
python3 scripts/simulate.py --users 1000 --clear

# audit the ledger and data integrity
python3 scripts/verify.py

# rebuild the site bundles and GitHub Pages assets
python3 scripts/build_site.py
```

No third-party Python packages are required — the engine is standard-library only.
Node is used solely to syntax-check and smoke-test the GitHub Pages JavaScript.

---

## Reproducing a competition

The competition is deterministic given stored data and a fixed clock:

- Strategy evaluation contains no randomness.
- The synthetic-fixture market generator is seeded (`random.Random(42)`).
- Simulated settlements use an hourly seed, so re-running within the same hour
  reproduces the same outcomes.

---

## Known limitations

**Data**

- `data/raw/` is empty in this checkout: no Kalshi collection has succeeded here, so
  all trades currently run on flagged synthetic fixtures. Collection is scheduled via
  GitHub Actions, where the API is reachable.
- The public trade tape does not return history older than a few hours, so historical
  fills cannot be validated against it; candlesticks are the historical price source.
- Native `KXNFLCOMBO` markets are RFQ-priced and rare, so the competition prices
  parlays as synthetic portfolios (flagged `SYNTHETIC_PARLAY`) rather than as native
  combos. The product-of-legs pricing assumes independence, which is wrong for
  correlated same-game legs and is flagged accordingly.
- Historical weather is unavailable (NWS serves forecasts only), so weather
  strategies are forward-only by construction.

**Model**

- Strategies that require inputs the system does not yet collect (weekday/primetime
  slot, division, rookie QB, DVOA/Elo ratings, per-player usage) cannot test their
  stated hypothesis. Those gaps are documented in each strategy rather than papered
  over with a proxy.
- The "model probability" in several strategies is derived from the market price
  itself, which guarantees a positive measured edge without containing independent
  information. Those entries say so explicitly.
- Partial fills and depth-walking are only as good as the order-book snapshots, which
  do not exist yet in this checkout.

**Process**

- One collection cycle captures a moment, not a continuous tape. Market movement
  between cycles is not observed.
- Competition history is preserved in the ledger, but no season has yet completed, so
  cross-season comparison has no data behind it.

---

## Next work

1. **Get real data in.** Run `collect.py --mode full` where the API is reachable, then
   confirm `data_provenance.real_kalshi_data_present` flips to `true` and the
   `UNVERIFIED_DATA` fixture flags disappear.
2. **Close the input gaps** that make strategies untestable: store the weekday/kickoff
   slot, division membership, starting-QB identity, and per-player usage from a
   verified source.
3. **Build an independent model probability** (ratings from stored game results) so
   "implied value" strategies stop being circular.
4. **Backtest against the candle archive** as it accumulates, and gate strategies on
   out-of-sample performance rather than in-sample fit.
5. **Model the maker path** so liquidity-provision strategies are charged maker fees
   and can actually rest orders.
6. **Add native combo support** once `KXNFLCOMBO` markets appear, replacing synthetic
   product pricing with the combo's own book.
7. **Season rollover**: freeze a completed competition, archive it under `history/`,
   and start a new one without touching the ledger.
