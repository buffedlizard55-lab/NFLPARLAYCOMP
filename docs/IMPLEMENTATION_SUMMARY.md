# Implementation Summary — NFL Parlay Trading Competition

## Completed

### Core Engine
- **Kalshi client** (`engine/kalshi_client.py`): read-only Trade API v2, no credentials, endpoints /exchange/status, /series, /events, /markets, /markets/{ticker}/orderbook, /series/{series}/markets/{ticker}/candlesticks, /markets/trades. Every fetch logged to `data/raw/kalshi/manifest.jsonl` with SHA-256.
- **Fees** (`engine/fees.py`): transcribed from https://kalshi.com/docs/kalshi-fee-schedule.pdf effective 2026-07-07, asserted by `tests/test_fees.py` 21 rows, formula round_up(M*0.07*C*P*(1-P)) taker, 0.0175 maker, multipliers KXNFLGAME=1, KXNFLCOMBO maker2 taker1.
- **Orderbook & Execution** (`engine/orderbook.py`, `engine/execution.py`): bid/ask spread, orderbook depth walking real levels, partial fills, liquidity checks (10% flagged, 50% rejected), slippage measured vs best, market status checks, fee at execution, no settlement fee, synthetic N-leg pays N fees.
- **Parlay** (`engine/parlay.py`): leg validation, synthetic pricing (portfolio of independent markets flagged SYNTHETIC_PARLAY with correlation warning) vs native COMBO (KXNFLCOMBO, RFQ-priced, rare, must all YES to pay $1), settlement arithmetic, per-leg result breakdown.
- **Strategies** (`engine/strategies.py`): 52 distinct strategies across 6 categories (MARKET_BASED, GAME_BASED, SITUATIONAL, STATISTICAL, CORRELATION, PROP_BASED), each meaningfully different, not just username randomization. Each documents: what info uses, entry, avoid, sizing, EV, why work/fail, evidence, sources (links). No randomness, deterministic, same inputs give same signals.
- **Competition** (`engine/competition.py`): cycle runner signals→orders→fills→settlement→ranks, lightweight users.json, performance_history, equity curve, ROI history, win/loss distribution, trade frequency, drawdown, open exposure. Added `generate_candidate_trades()` sampling 200 users, building rich candidate legs with contract=ticker, proposed_entry_price, current_verified_price, expiration_date/settlement_date/close_time/open_time, position_size, liquidity/bid/ask/spread, model_prob, source_url/verification_url, official_source, verification_info; `save_upcoming_trades()` writes `data/competition/upcoming_candidates.json`; run cycle generates candidates before execution.
- **Ledger** (`engine/ledger.py`): hash-chained append-only ledger, O(1) appends, tail cached, single source of truth, `latest_trades()` collapses to latest state, hash chain valid verified.
- **Verification** (`engine/verify.py`): chain, manifest, per-trade reproducibility, state checks, flags for missing/unverified/suspicious/liquidity/impossible/API/duplicate/calculation/settlement/data-source conflicts, never hidden, aggregated by type for 1000-user readability.

### Site Builder & Pages
- **Bundles** (`engine/site_builder.py`): writes only to `docs/site_data/` (served copy is only copy), no duplicate root bundle. Leaderboard projection (no strategy long text duplication), shared `trades/index.json` compact rows filtered by user_id, per-user summary files pointing to shared index, strategy explanation served once from `strategies.json`, verification flags aggregated.
- **Trades bundles**: `trades/index.json` every trade compact verifiable, `trades/recent/upcoming/closed/rejected` bounded 200 full records, `trades/candidates.json` candidate signals, `trades/upcoming_combined.json` candidates+executed, `trades/ledger_summary` counts distinct vs ledger entries.
- **Navigation grouped per spec**: Competition (Overview, Leaderboard, Upcoming Trades, Candidate Signals, Recent Trades, Markets), Strategies (Library, Performance, Research), Users (Profiles, Trade History), Verification (Trade Verification, Data Sources, Flags), History (Scalability, Architecture, Competition Period).
- **Frontend** (`docs/index.html`, `app.js`, `style.css`, `.nojekyll`): search/sort/filter/pagination, category filter, lifecycle filter, trade drill-down with full record (market ticker, event ticker, contract, side, entry/exit price, timestamps, expiration, quantity, position size, implied prob, liquidity, bid/ask, spread, slippage, fees, PnL, ROI, result, official source, verification), reconciliation arithmetic, equity curve sparkline, ROI over time, win/loss distribution, trade frequency, verification path Leaderboard→User→Trade→Official Source with links to https://kalshi.com/markets/{ticker} and https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}.
- **Pages deploy**: `docs/` with `.nojekyll`, relative fetch paths, `pages.yml` workflow uploads `./docs` as artifact, legacy root forwarder `index.html` → `docs/` with root `.nojekyll` to disable Jekyll, verified live at https://buffedlizard55-lab.github.io/NFLPARLAYCOMP/docs/ (redirect from root).

### Scalability
- Tested 5→10→15→25→30→50→70→100→250→500→750→1000 users without redesign, architecture shared market data + hash-chained ledger + lightweight users.json, market data loaded once, ledger tail cached, O(1) trade index, no per-user market duplication, site_data users/ 1000 JSON files under _fresh_dir cleanup, leaderboard pagination 25/50/100, trade index compact projection.
- Measured: 5 users 0.01s, 50 0.01s, 250 0.05s, 500 0.15s, 1000 0.20s (one cycle creating trades, synthetic fixture).

### Data Provenance & Verification
- Real verified market data when `data/raw/kalshi/` present (populated by GitHub Actions where API reachable), flagged synthetic otherwise (offline sandbox TLS blocked, expected).
- Distinguishes real verified data vs simulated trades clearly: `data_provenance.real_kalshi_data_present`, `settlement_result_source` OFFICIAL vs SIMULATED vs PARTIAL vs UNKNOWN, per-leg breakdown, SIMULATED_SETTLEMENT flag, UNVERIFIED_DATA flag.
- Every trade records: market ticker, event ticker, contract, side, entry/exit price, timestamps, expiration, quantity, position size, implied prob, liquidity, bid/ask, spread, slippage, fees, PnL, ROI, result, source file, SHA-256, source_url, verification_url, official_source, verification_info.
- Research sources for discovery only (Reddit r/sportsbook, r/nfl, academic Wolfers & Zitzewitz 2004, ESPN, NWS, Kalshi docs), not pricing. Actual pricing from verified Kalshi data only. No fabricated prices/markets/timestamps/liquidity, no paid APIs, no estimated historical prices as actual.

## Verified

- **Tests**: `tests/test_all.py` runs 4 gates: python tests (103 tests, 3 skipped), ledger+verification, fetch manifest, front-end smoke (Node). All gates passed after fixes.
  - `test_app_js_has_valid_syntax`: Node --check passes, no absolute "/site_data/" paths, relative fetch works whether docs/ is artifact root or not.
  - `test_every_strategy_documents_the_required_sections`: Uses, Entry, size present, explanation >150 chars, sources links.
  - `test_bundles_resolve_relative_to_docs`: relative paths only.
  - `test_site.py` smoke: loadOverview, loadLeaderboard, loadMarkets, loadStrategies, loadVerification, loadHistory, loadTrades, loadProfile for 25 users without error.
- **Ledger**: chain valid, count 500 distinct trades, 500 ledger entries for 1000-user synthetic run, hash chain intact.
- **Manifest**: 6 rows, 0 malformed, status_counts {0:6} for synthetic fixtures.
- **Site**: docs/app.js syntax OK, no absolute bundle paths, bundles resolve relative to docs/, 1000-user leaderboard pages, candidates.json 104 candidates with rich fields, upcoming_combined.json, index.json compact.
- **Pages**: live at https://buffedlizard55-lab.github.io/NFLPARLAYCOMP/docs/ (forwarder from root), competition.json, candidates.json accessible, grouped nav renders.

## Remaining / Future Work

- **Real Kalshi collection**: offline sandbox blocks external API TLS EOF, so synthetic fixtures flagged UNVERIFIED_DATA. Real collection via GitHub Actions (collect.yml) where API reachable — needs manual trigger or schedule to populate data/raw/kalshi/, then competition runs on real verified data.
- **Settlement**: trade tape no history older than few hours, so candles are historical source. When no official result stored, outcome drawn from market-implied probability, stamped SIMULATED_SETTLEMENT. Need collection cycle capturing settled markets to get official result fields.
- **Native COMBO**: KXNFLCOMBO rare, so parlays priced as synthetic portfolios flagged SYNTHETIC_PARLAY with correlation warning. Need RFQ handling when COMBO markets appear.
- **Strategy inputs**: strategies requiring weekday/primetime, division, rookie QB, DVOA/Elo ratings, per-player usage cannot test hypothesis without that input — documented per strategy, falsification targets. Need additional NFL metadata loaders (e.g., team ratings, depth charts) from public sources.
- **History preservation**: ledger preserves history, but no season completed yet. Need to run full season (2026-09 to 2027-02) cycles, preserve historical competitions for comparing strategies, users, seasons, markets, trade types, performance, consistency, without overwriting previous competition data.
- **Pages source**: repository still on legacy build_type legacy, source path "/". Required fix (one click owner): Settings → Pages → Source: GitHub Actions, which deploys docs/ directly via pages.yml and makes root forwarder unnecessary. Until then, root .nojekyll + forwarder enables reachability.

## Known Limitations

- **Data**: data/raw empty in offline checkout, so synthetic fixtures flagged UNVERIFIED_DATA. Real collection via GitHub Actions where API reachable. Trade tape no history older than few hours, so candles are historical source. Native KXNFLCOMBO rare, so parlays priced as synthetic portfolios flagged SYNTHETIC_PARLAY with correlation warning.
- **Model**: strategies requiring weekday/primetime, division, rookie QB, DVOA/Elo ratings, per-player usage cannot test hypothesis without that input — documented per strategy. Model prob in several strategies derived from market price itself, circular — documented as honesty note, evidence none established.
- **Process**: one collection cycle captures moment, not continuous tape. Competition history preserved in ledger, but no season completed yet. Settlement provenance SIMULATED when no official result stored — clearly labeled, not presented as verified result.
- **Pages**: legacy root-path build until owner switches to GitHub Actions source. Root forwarder + .nojekyll mitigates, but ideal is Actions deploy. Artifact size 9MB for 1000 users (4MB users/) within limits but grows with users — future may need pagination for user profiles bundle or on-demand loading.
- **Scalability**: architecture supports 1000+ without redesign, but site_data/users/ 1000 files may hit GitHub Pages file count limits at larger scales — future could bundle users into pages or use IndexedDB.

## MasterSite Integration

Reviewed https://buffedlizard55-lab.github.io/MasterSite/ (52 verified sites):
- Markets & Trading Research 9, Sports Data & Scoreboards 18.
- NFL Injury Report (https://buffedlizard55-lab.github.io/NFLInjuryReport/): live injury alerts from free public sources, official nfl.com designations, ESPN timestamps — cross-check injury data, injury fade strategy.
- NFLComp (https://buffedlizard55-lab.github.io/NFLComp/): autonomous NFL betting strategy research & competition, 60 personas, Elo, DVOA — strategy discovery reference, not price source.
- Commodities (https://buffedlizard55-lab.github.io/Commodities/): evidence-first paper-trading lab for Kalshi event contracts, hash-chained ledger, execution-realism checks vs trade tape, median 1.00c gap, 361 evidence-bound ledger events — ledger design reference.
- Sports Pred, NFL Scoreboard, Weather — schedule, venue, forecast verification.
- Integration via GitHub Actions where API reachable; offline checkout flags UNVERIFIED_DATA rather than inventing.

## How to Verify a Trade

1. Leaderboard → click username → User Profile → Trade History
2. Click trade row → full record: every leg, every price, snapshot file, fee model, official source link
3. Official source: https://api.elections.kalshi.com/trade-api/v2/markets/{ticker} + https://kalshi.com/markets/{ticker}
4. Reconcile: payout - cost - fees = PnL checkable, displayed in detail
5. Flags: missing data, unverified, liquidity, impossible execution — never hidden
6. Ledger: data/competition/ledger.jsonl hash-chained, SHA-256, O(1) appends, single source of truth

## Commands

```bash
python3 scripts/collect.py --mode full          # real data (works in Actions)
python3 scripts/simulate.py --users 1000 --clear
python3 scripts/build_site.py
python3 scripts/test_all.py
```

Site: https://buffedlizard55-lab.github.io/NFLPARLAYCOMP/docs/
Repo: https://github.com/buffedlizard55-lab/NFLPARLAYCOMP
