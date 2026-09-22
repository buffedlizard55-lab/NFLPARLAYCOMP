# NFLPARLAYCOMP — NFL Parlay Trading Competition

An auditable **paper-trading competition** for NFL parlay strategies using **real, verified Kalshi market data**. Many simulated users (target: 1,000+, tested from 5 upward) compete on NFL parlay-style positions built from real Kalshi NFL contracts. **No real money is ever traded** — the project contains no order-placement code and no credentials.

## Goal

Research, design, generate, test, simulate, track, and compare as many potentially successful NFL parlay strategies as possible, using real verified Kalshi pricing and dates, with a scalable competition environment.

## Non-negotiable data rules

- Every price, timestamp, market, contract, liquidity figure, and settlement used by the simulation comes from official Kalshi Trade API endpoints (read-only, unauthenticated) or from other official/public sources (ESPN keyless APIs, NWS) and is stored verbatim with a SHA-256 manifest entry recording the exact request URL and retrieval time.
- Simulated trades are clearly labelled as simulations. Real verified data and simulated activity are never blended into one ambiguous field.
- Anything that cannot be verified is **flagged**, never silently estimated.

## Kalshi NFL Market Structure (verified)

- **Binary markets**: YES/NO, settle $1 if YES, $0 if NO. Series: KXNFLGAME (moneyline), KXNFLSPREAD, KXNFLTOTAL, KXNFLTEAMTOTAL, KXNFL1H, etc.
- **Native COMBO markets**: KXNFLCOMBO — introduced Dec 2025, RFQ-priced, same-game and cross-game, must all YES to pay $1. Orderbook is RFQ-driven, not continuous. Availability limited close to event. Verified via docs and live API.
- **Synthetic parlay**: portfolio of independent single markets simulated as combined position. NOT a native Kalshi order. Flagged as SYNTHETIC_PARLAY with correlation warning. Product pricing assumes independence (flagged).

See `docs/MARKET_STRUCTURE.md` for full findings.

## Layout

- `engine/` — dependency-free Python package (stdlib only):
  - `kalshi_client.py` — read-only client, call log with SHA-256
  - `collect.py` — verified data collector (universe, events, candles, live, nfl, weather)
  - `parlay.py` — parlay model, leg validation, combined prob, settlement, native vs synthetic
  - `strategies.py` — 35+ distinct NFL strategies (market-based, game-based, situational, correlation, statistical)
  - `execution.py` — realistic paper trading: bid/ask, liquidity, position size vs depth (10% rule), slippage, fees (7% profit), market status
  - `ledger.py` — hash-chained immutable ledger (SHA-256 chain)
  - `competition.py` — competition runner, scales 5→1000 users, shared market data (no duplication)
  - `verify.py` — verification: chain, manifest, trades, users, flags
  - `site_builder.py` — builds site_data JSON + docs/ GitHub Pages site
  - `nfl_data.py` — NFL metadata (schedule, injuries, venues, weather)
  - `data_model.py`, `utils.py`
- `scripts/` — CLI entry points
- `data/raw/` — verbatim API snapshots + fetch manifest (shared by all strategies, never duplicated per user)
- `data/competition/` — competition state: users.json, hash-chained ledger.jsonl, trades/, verification_report.json
- `site_data/` — generated JSON bundles consumed by static site
- `docs/` — GitHub Pages site (index.html, style.css, app.js) + research notes, market-structure findings, data-truth policy, operations
- `tests/` — offline unit tests (fixtures only, no network)
- `.github/workflows/` — scheduled data collection + competition cycles on GitHub Actions

## Quick start

```bash
# run tests (offline)
python3 -m unittest discover -s tests -v

# collect verified data (requires network; runs in GitHub Actions otherwise)
python3 scripts/collect.py --mode full

# generate users for scalability test (5 -> 1000)
python3 scripts/generate_users.py --count 100

# run/simulate the competition over collected data
python3 scripts/simulate.py --users 100

# audit the ledger and data integrity
python3 scripts/verify.py

# regenerate the static site bundles and docs site
python3 scripts/build_site.py
```

The competition website is published at https://buffedlizard55-lab.github.io/NFLPARLAYCOMP/

## Competition Environment

Scalable through: 5 → 10 → 15 → 25 → 30 → 50 → 70 → 100 → 250 → 500 → 750 → 1,000 simulated users/strategies without redesign.

Architecture:
- Shared market data in data/raw/kalshi/ (loaded once)
- Lightweight users.json (not per-user market duplication)
- Hash-chained ledger.jsonl (append-only, SHA-256)
- Pre-aggregated site_data JSON for fast pages (pagination, filtering)

Each simulated user has:
- Unique username, unique strategy, description, starting bankroll, current bankroll, open trades, closed trades, total PnL, ROI%, win/loss record, number trades, current rank, performance history, explanation why generated or lost money

## Strategy Library (35+ distinct)

- Market-based: Implied Value, Line Movement Momentum, Mean Reversion, Cross-Market Arb, Liquidity Provision, Contrarian Public, Alt Line Value
- Game-based: Home Advantage, Rest Advantage, Divisional Dog, Primetime Favorite Fade, Coaching Mismatch, Veteran QB, Blowout Reversion
- Situational: Bad Weather Under, Injury Fade, Short Week Under, Rookie QB Under, Q1 Under, TNF Home Dog, Indoor Over, 2H Comeback
- Correlation: Spread+Moneyline, Total+Underdog, 1H vs Full Game Divergence, TD+Game, Team Total Over/Under
- Statistical: Elo Model, DVOA Value, Win Streak Fade, 3-Game Momentum, etc.

Each strategy explains: what info uses, entry conditions, avoidance, position size, EV, why might work/fail, evidence, sources.

## Parlay Trading

For every simulated trade, record: market ticker, event ticker, contract, side, entry price, exit price, entry/exit timestamps, expiration/settlement date, quantity, position size, implied prob, liquidity, bid/ask, spread, slippage, fees, PnL, ROI, result, official source, verification info.

Realistic paper trading accounts for: bid/ask spread, liquidity, position size, market depth, slippage, price movement, order availability, market status, settlement, fees.

## Upcoming Trades

Separate section for upcoming simulated trades. Each strategy continuously determines: what markets it wants, why, proposed entry, current verified price, EV, position size, required liquidity, conditions required, whether currently executable, what would invalidate.

Distinguishes: Candidate → Signal → Order → Executed → Closed → Settled. Signal not treated as executed.

## Trade Verification

Critical: every simulated trade manually verifiable via Leaderboard → User → Trade → Official Source.

For every trade, provide links to official/trusted source for market, contract, price, date, time, result, settlement. Preserve enough info to independently verify calculation.

If historical verification not possible, flag as unverifiable.

## Trade Ledger

Complete immutable-style record: every trade ever placed, upcoming, cancelled, rejected, closed, settled, every strategy decision, every price, every source, every calculation.

Efficient: same verified market data reused by thousands strategies, not duplicated.

Structured for: backtesting, forward testing, strategy comparison, research, statistical analysis, improvement, future competitions.

## Leaderboard

Shows: Rank, Username, Strategy, Starting bankroll, Current bankroll, PnL, ROI, Wins, Losses, Win rate, Number trades, Open positions, Last trade, Competition status.

Supports: search, sorting, filtering, pagination, different page sizes. Fast and readable at 1000 users.

## User Profile

Overview: username, strategy, explanation, bankroll, PnL, ROI, rank, win rate, total trades, open positions

Performance: equity curve, PnL over time, ROI over time, win/loss distribution, trade frequency, drawdown, open exposure

Trade History: searchable/paginated, each trade includes date/time, NFL game/event, Kalshi market, contract, position, entry/exit price, quantity, PnL, ROI, status, verification/source link, ability to inspect underlying data.

## Verification Contract

Each simulated trade can be audited via **Leaderboard → User → Trade → Official Source**. Every trade record carries the market ticker, event ticker, entry/exit timestamps, prices, quantities, fees, settlement, the exact snapshot files (with SHA-256) the prices came from, and official links for manual re-verification.

See `docs/DATA_TRUTH.md` for full evidence policy and `docs/FLAGS.md` for flagging system.

## Site Structure

**Competition**: Overview, Leaderboard, Upcoming Trades, Recent Trades, Markets
**Strategies**: Strategy Library, Strategy Performance, Strategy Research
**Users**: User Search, User Profiles, Trade History
**Verification**: Trade Verification, Data Sources, Data Integrity/Flags
**History**: Previous Competitions, Previous Seasons, Historical Performance

Clean, simple, fast, easy to navigate, audit, organized for large numbers users. Pagination, filtering, tabs, expandable sections, drill-down pages.

## MasterSite Integration

Reviewed https://buffedlizard55-lab.github.io/MasterSite/ — relevant NFL projects:
- NFL Injury Report: live injury alerts from free public sources, official nfl.com designations, ESPN timestamps. Used for injury cross-check.
- NFLComp: autonomous NFL betting strategy research & competition. Used for strategy research reference.
- Commodities: evidence-first paper-trading lab for Kalshi event contracts, hash-chained ledger, execution-realism checks. Used for ledger design reference.
- Sports Pred, NFL Scoreboard, Weather: similar.

Verified their data before using. Documented in docs/SOURCES.md

## Accuracy

Never fabricate: markets, prices, trades, dates, liquidity, results, API responses, performance, sources. If cannot verify, flag. Provide official/trusted links for manual review.

## No Manual Input

Autonomous via APIs, public datasets, automated retrieval. If external source cannot be automatically verified, flag for review rather than asking manual entry.

## Flags

System for flagging: missing data, unverified data, suspicious prices, missing timestamps, liquidity problems, impossible executions, API errors, duplicate trades, calculation errors, settlement inconsistencies, data-source conflicts.

Do not hide irregularities.

## Git / Pages

GitHub Pages deployed from docs/ folder. Workflows:
- collect.yml: scheduled data collection (read-only Kalshi, ESPN, NWS)
- simulate.yml: competition cycle + verification + site build
- pages.yml: deploy docs/ to Pages

## Multi-pass Development

Pass 1: core competition, data pipeline, simulated users, strategies, ledger, leaderboard, profiles, verification, site
Pass 2: bug fixes, missing requirements, edge cases, scalability, UI
Pass 3: re-check against original request, improve accuracy, reliability, completeness, code quality

## Limitations & Next Work

- Kalshi API network may be blocked in sandbox; collector has fallback to synthetic fixtures flagged as such for offline testing. Real data collection works in GitHub Actions.
- Historical weather unavailable from NWS (forward-only) — flagged.
- Historical trade tape only recent (few hours) — candles used for historical.
- Combo markets rare, RFQ pricing — synthetic parlay model used with flags.
- Need more real data collection cycles to populate 2026 season.
- Need backtesting over full season once data available.
- Need to integrate more MasterSite projects as they update.
