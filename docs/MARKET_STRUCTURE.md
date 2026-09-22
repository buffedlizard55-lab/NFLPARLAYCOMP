# Kalshi NFL Market Structure Findings

Verified 2026-09-22 via official docs and live API observation (see data/raw/kalshi/universe.json when collected).

## Series

Discovered from GET /series?category=Sports filtered to KXNFL prefix:

- Core game series (all markets candle-archived):
  - KXNFLGAME: moneyline / game winner
  - KXNFLSPREAD: team to win by more than X.5
  - KXNFLTOTAL: game total over X.5
  - KXNFLTEAMTOTAL: team total points
  - KXNFLWINMARGIN: win margin ranges
  - KXNFL1H, KXNFL1HWINNER, KXNFL1HSPREAD, KXNFL1HTOTAL, KXNFL1HTEAMTOTAL: first half markets
  - KXNFLCOMBO: native Kalshi parlay/combo markets (rare, marquee games)

- Prop game series (top N by volume per event candle-archived, documented limitation):
  - KXNFLANYTD, KXNFLTD, KXNFLTEAMTD, KXNFLTEAMFIRSTTD, KXNFLFIRSTTD, KXNFLFIRSTTDTEAM, KXNFLTOTALTD, KXNFL2TD, KXNFLCOMPETE (will player compete), KXNFLMATCHUP, KXNFL1Q, KXNFL2Q, etc., KXNFLBOTH, KXNFLOT, KXNFLTIES, KXNFLSFTY, KXNFL2PTCONV, KXNFLGAMESPECIALS, KXNFLGAMETD, KXNFLGAMEFG, KXNFLGAMESACK, KXNFLGAMETO, KXNFL1QBTTS, KXNFL1HFT, KXNFLDSTTD, KXNFLFG, KXNFL60YARDFGS, KXNFL4DCONV

## Event ticker

Format: KXNFLxxx-YYMONDD<AWAY><HOME>
Example: KXNFLGAME-26SEP20CLETB
- YYMONDD: 26SEP20 = Sep 20 2026
- AWAY: CLE, HOME: TB (away first, home second — verified against ESPN away at home naming)
- Season window: 2026 season is -26SEP.. through -26DEC plus -27JAN/-27FEB postseason

## Market ticker

Format: {series}-{event_slug}-{suffix}
Example: KXNFLGAME-26SEP20CLETB-TB (Tampa Bay wins)
- Suffix often team abbreviation or line: -TB, -TB-3.5, -O45.5, etc.

## Market fields (verified)

- ticker, event_ticker, series_ticker, title, subtitle, category (Sports)
- status: unopened, open, active, closed, settled
- market_type: binary
- yes_bid, yes_ask, no_bid, no_ask, last_price, previous_price
- volume, volume_24h, open_interest, liquidity
- open_time, close_time, expiration_time, expected_expiration_time
- result: yes/no when settled
- rules_primary: settlement rules text

## Orderbook

- GET /markets/{ticker}/orderbook?depth=100
- Returns yes bids and no bids only (no asks returned) because binary market: bid for YES at X equivalent to ask for NO at 1-X
- For execution realism, we use yes_bid/yes_ask if available, else last_price

## Candlesticks

- GET /series/{series}/markets/{ticker}/candlesticks?start_ts=&end_ts=&period_interval=60
- period_interval: 1 (1min), 60 (hourly), 1440 (daily)
- Returns price open/high/low/close/mean, yes_bid close, yes_ask close, volume_fp, open_interest_fp
- Historical: markets settled before historical cutoff only via /historical/... (not yet implemented, flagged)

## Trades tape

- GET /markets/trades?ticker=&limit=
- Public trade tape, but NOTE verified 2026-09-22: does NOT return trades older than few hours even with min_ts/max_ts, so historical fills cannot be validated against tape — candlesticks are verified historical source. Tape IS used for execution-realism checks of fills near collection time.

## Combo / Parlay

- Kalshi does NOT offer traditional sportsbook parlays
- Offers COMBO feature introduced Dec 2025: bundle multiple YES/NO contracts into single position via RFQ (Request for Quote)
- Combo is its own market with dedicated orderbook (RFQ-driven, not continuous)
- All legs must be correct to receive $1 payout, else $0
- Pricing: RFQ system, market-driven, not product of legs (product assumes independence, flagged)
- Availability: limited close to event start, same-game combos more common than cross-game, pricing via institutional market makers
- Our simulation:
  - NATIVE_COMBO: when KXNFLCOMBO market exists, use its own bid/ask
  - SYNTHETIC_PARLAY: portfolio of independent markets, flagged, correlation warning, product pricing with discount

## Fees (verified against the official fee schedule)

Source: **Kalshi Fee Schedule, "Last updated and effective: July 7, 2026"**
https://kalshi.com/docs/kalshi-fee-schedule.pdf  (landing page: https://kalshi.com/fee-schedule)

Official formulas, quoted from the schedule:

| Order type | Formula | Charged when |
| --- | --- | --- |
| Taker (immediately matched) | `fees = round up(M x 0.07 x C x P x (1-P))` | On execution |
| Maker (rests on the book) | `fees = round up(M x 0.0175 x C x P x (1-P))` | When ultimately executed |
| Settlement | *"There is no settlement fee."* | — |
| Membership | *"There is no membership fee."* | — |

Where `P` = contract price in dollars, `C` = contracts, `M` = per-series multiplier
(default 1). Rounding is up, so that fee + positionCost lands on a centicent.

Verified rows of the published "General Trading Fees Table" (100 contracts), which
`tests/test_fees.py` asserts against:

| Price | Published fee / 100 | | Price | Published fee / 100 |
| --- | --- | --- | --- | --- |
| $0.01 | $0.07 | | $0.50 | $1.75 |
| $0.10 | $0.63 | | $0.60 | $1.68 |
| $0.25 | $1.32 | | $0.75 | $1.32 |
| $0.45 | $1.74 | | $0.99 | $0.07 |

The fee is symmetric around $0.50 and peaks there ($1.75 per 100 contracts).

**Per-series multipliers** (same schedule, "Non-Standard Fees" table):

| Series | Description | Maker M | Taker M |
| --- | --- | --- | --- |
| KXNFLGAME | Professional Football Game | 1 | 1 |
| KXNFLCOMBO | Combos (excluding uncorrelated NFL Championship combos) | 2 | 1 |

**Consequences applied in this project (`engine/fees.py`):**

- Fees are charged **on execution and are not contingent on the outcome** — a losing
  trade still pays its entry fee. (An earlier revision of this project charged
  "7% of profit at settlement", which charged losers nothing and mis-stated winners.
  That model was wrong and has been replaced.)
- A synthetic N-leg parlay is N separate orders, so it pays **N fees**. This is the
  real source of the "fees compound per leg" effect described in the strategy notes.
- Arithmetic is done in `decimal.Decimal`. In binary floating point
  `0.07 * 100 * 0.6 * 0.4 == 1.6800000000000002`, which would round **up** to $1.69
  and contradict the published $1.68.
- Our simulated orders are marketable (they cross the spread), so they are takers.
- Fees scale with `P x (1-P)`: cheap longshots and deep favourites are cheap to
  trade, mid-priced contracts are the most expensive.

## Verification

- Every market snapshot stored with source_url, fetched_at, SHA-256 manifest
- Official links:
  - API: https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}
  - Web: https://kalshi.com/markets/{ticker}
  - Fee schedule (PDF): https://kalshi.com/docs/kalshi-fee-schedule.pdf
