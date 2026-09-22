# Flags System

Every irregularity is flagged, never hidden.

## Flag types

- MISSING_DATA: required data not found in verified snapshots
- UNVERIFIED_DATA: data exists but cannot be verified from official source
- SUSPICIOUS_PRICE: price out of bounds [0.01,0.99] or implausible move
- MISSING_TIMESTAMP: timestamp missing or unparsable
- LIQUIDITY_PROBLEM: low liquidity, wide spread, position size >10% of liquidity
- IMPOSSIBLE_EXECUTION: market status not executable, position too large
- API_ERROR: Kalshi API error, network failure, manifest malformed
- DUPLICATE_TRADE: duplicate trade_id in ledger
- CALCULATION_ERROR: PnL, ROI, EV calculation error or missing
- SETTLEMENT_INCONSISTENCY: missing settlement for leg, result conflict
- DATA_SOURCE_CONFLICT: ticker mismatch, conflicting sources
- WEATHER_UNAVAILABLE: historical weather unavailable (forward-only)
- INJURY_UNAVAILABLE: injury data unavailable
- ORDERBOOK_MISSING: no bid/ask/last available
- CANDLE_MISSING: no candlestick history for market
- COMBO_NOT_NATIVE: native combo pricing RFQ-driven, not continuous
- SYNTHETIC_PARLAY: synthetic parlay not native Kalshi combo, correlation warning
- SIMULATED_SETTLEMENT: no official Kalshi result stored; outcome drawn from market-implied probability (medium — always shown next to the trade)
- OFFICIAL_SETTLEMENT: outcome read from the settled market's official `result` field
- DATA_PROVENANCE: which class of data a field came from — real / derived / simulated

## Severity

- high: blocks execution, invalidates trade, breaks chain
- medium: warns, may affect PnL accuracy, needs review
- low: informational, e.g., synthetic fixture, forward-only limitation

## Storage

Flags stored in:
- Trade record flags array
- User flags array
- Competition flags array
- data/competition/verification_report.json
- site_data/verification.json (for UI)

## UI

Flags displayed in verification section with color coding:
- high: red left border
- medium: orange
- low: gray

## No silent substitution

If required information unavailable, flag limitation instead of inventing it.

## Provenance rules used by the simulator

- A price is only used if it came from a verified snapshot. Where a value is missing,
  the trade is rejected or the limitation is flagged — never filled in with an estimate.
- Settlement is stamped `OFFICIAL` or `SIMULATED` per trade, with the per-leg source
  recorded in `settlement_leg_sources`. A simulated settlement is never presented as a
  result.
- Order-book depth that was not available is disclosed via `ORDERBOOK_MISSING` rather
  than assumed.

## Where flags surface

| Location | Contents |
| --- | --- |
| `data/competition/ledger.jsonl` | flags array on each chained trade entry |
| `data/competition/verification_report.json` | full audit, written by `scripts/verify.py` |
| `site_data/verification.json` | the same audit, consumed by the site's Verification page |
| User record | per-user `flags` array (e.g. strategy evaluation errors) |
| Competition cycle result | `market_flags` (e.g. synthetic-fixture warning) |
