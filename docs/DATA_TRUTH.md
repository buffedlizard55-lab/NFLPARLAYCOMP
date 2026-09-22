# Data Truth Policy

## Non-negotiable rules

- Every price, timestamp, market, contract, liquidity, settlement comes from official Kalshi Trade API v2 (read-only, unauthenticated) or other official/public sources (ESPN keyless, NWS) and is stored verbatim with SHA-256 manifest entry recording exact request URL and retrieval time.
- Simulated trades are clearly labeled as simulations. Real verified data and simulated activity never blended into one ambiguous field.
- Anything that cannot be verified is flagged, never silently estimated.

## Data classes

- **SOURCE_DATA**: verbatim API responses stored in data/raw/ with manifest SHA-256. Example: Kalshi market snapshot, ESPN scoreboard, NWS forecast.
- **DERIVED_DATA**: 1:1 compact projections preserving all fields with short keys, schema documented, hash-chained to source via manifest. Example: candle compact rows.
- **MODEL_OUTPUT**: strategy signals, expected value calculations, derived from SOURCE_DATA but not itself source.
- **SIMULATED**: paper trades, PnL, ROI, settlement simulations. Clearly labeled.
- **UNVERIFIED**: data that cannot be verified from official source, flagged.

## Kalshi API verification

Official endpoints (https://docs.kalshi.com/):
- GET /exchange/status
- GET /series?category=Sports
- GET /events?series_ticker=KXNFL...
- GET /markets?event_ticker=...
- GET /markets/{ticker}
- GET /markets/{ticker}/orderbook
- GET /series/{series}/markets/{ticker}/candlesticks
- GET /markets/trades

All calls logged to data/raw/manifest.jsonl with URL, status, bytes, SHA-256, retrieval time (UTC ISO-8601).

## NFL metadata

- ESPN keyless site API: https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard, /injuries
- Used only for home/away, kickoff cross-check, scores, venue, indoor flag, injuries — NOT for prices.
- NWS api.weather.gov: weather forecasts forward-only, historical unavailable (flagged).

## Parlay model truth

- Kalshi binary markets: YES/NO, settle $1/$0.
- Native COMBO markets (KXNFLCOMBO): introduced Dec 2025, RFQ-priced, same-game and cross-game, must all resolve YES to pay $1. Orderbook is RFQ-driven, not continuous. Availability limited close to event. Verified via docs and live observation.
- Synthetic parlay: combining independent single markets in paper portfolio. NOT a native Kalshi order. Payoff product of legs if all win, else loss. Must be flagged as SYNTHETIC_PARLAY with correlation warning.

## Cash-flow model (what the money actually does)

Every trade moves cash in exactly two steps, and the ledger records both:

| Step | Bankroll effect | Fields recorded |
| --- | --- | --- |
| Execution | `-= (cost + entry fees)` where `cost = price x contracts` | `position_size_dollars`, `fees`, `total_debit_dollars`, `entry_price_combined` |
| Settlement | `+= payout` where `payout = contracts x $1` if every leg wins, else `$0` | `payout_dollars`, `contracts`, `cash_in_dollars` |

So a trade's contribution to the bankroll is exactly its recorded `pnl_dollars`:

```
pnl_dollars = payout_dollars - position_size_dollars - fees
```

`tests/test_accounting.py` re-derives this from the stored fields, and
`engine/verify.py` re-checks it on every settled ledger entry at audit time
(flagging `CALCULATION_ERROR` if a stored PnL is not reproducible).

Fees follow the official schedule (`engine/fees.py`) and are charged **at execution,
win or lose**; there is no settlement fee.

### Slippage

Executing at the quote already means crossing the spread, so the spread is **not**
charged a second time as slippage. Additional slippage only occurs when an order is
larger than the depth resting at the best price. Therefore:

- With a verified order-book snapshot: the order **walks real levels**
  (`engine/orderbook.py`), and `slippage_vs_best` is the measured difference between
  the average fill price and the best price.
- Without a snapshot: the fill is modelled at top of book, `slippage_assumed` is 0,
  and the trade carries an `ORDERBOOK_MISSING` flag recording that depth was not
  modelled. It is never replaced by an invented estimate.

A leg whose size exceeds the resting depth is **partially filled**, not assumed
filled; the shortfall is flagged `LIQUIDITY_PROBLEM`.

## Settlement provenance

A settlement is one of two things, and every settled trade says which:

| `settlement_result_source` | Meaning |
| --- | --- |
| `OFFICIAL` | Result read verbatim from the `result` field of a settled Kalshi market. |
| `SIMULATED` | No official result was stored, so the outcome was drawn from the market-implied probability. Carries a `SIMULATED_SETTLEMENT` flag. |
| `PARTIAL` | Some legs had official results, others were drawn. |
| `UNKNOWN` | Provenance not recorded (legacy record). |

Signals are **never** treated as executed trades. A `SIGNAL`/`ORDER` record carries no
position size; the verifier flags `CALCULATION_ERROR` if one ever does.

## Verification path

Leaderboard → User → Trade → Official Source

Each trade record carries:
- market ticker, event ticker, series ticker
- entry/exit timestamps, prices, quantities, fees, settlement
- snapshot files with SHA-256
- official links: https://api.elections.kalshi.com/trade-api/v2/markets/{ticker} and https://kalshi.com/markets/{ticker}

## Flags

See docs/FLAGS.md

## No hallucinations

Never fabricate:
- Markets, prices, trades, dates, liquidity, results, API responses, performance, sources

If cannot verify, flag.
