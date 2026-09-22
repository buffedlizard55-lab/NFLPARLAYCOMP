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

## Fees

- 7% of profit (verified from docs: https://docs.kalshi.com/getting_started/fee_rounding)
- Fee rounding rules per docs
- Our simulator: fee = 7% * profit per contract, estimated, flagged if docs unavailable

## Verification

- Every market snapshot stored with source_url, fetched_at, SHA-256 manifest
- Official links:
  - API: https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}
  - Web: https://kalshi.com/markets/{ticker}
