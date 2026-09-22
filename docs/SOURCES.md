# Data Sources

## Kalshi (primary, price source)

- Base URL: https://api.elections.kalshi.com/trade-api/v2 (fallback https://external-api.kalshi.com/trade-api/v2)
- Docs: https://docs.kalshi.com/
- Endpoints used:
  - GET /exchange/status — exchange health
  - GET /series?category=Sports — NFL series catalog (KXNFL prefix)
  - GET /events?series_ticker=KXNFLGAME&status=open — game events
  - GET /markets?event_ticker=KXNFLGAME-... — markets per event
  - GET /markets/{ticker} — single market
  - GET /markets/{ticker}/orderbook?depth=100 — orderbook for execution realism
  - GET /series/{series}/markets/{ticker}/candlesticks?start_ts=&end_ts=&period_interval=60 — hourly candles (historical)
  - GET /markets/trades?ticker=&limit= — trade tape for execution-realism checks (recent only, not historical)
- Authentication: none (public endpoints)
- Rate limiting: 0.12s pause + exponential backoff on 429/5xx per docs
- Verification: every response logged to manifest.jsonl with SHA-256, URL, timestamp
- Market structure findings (verified 2026-09-22):
  - Series: KXNFLGAME (moneyline), KXNFLSPREAD, KXNFLTOTAL, KXNFLTEAMTOTAL, KXNFLWINMARGIN, KXNFL1H, KXNFLCOMBO (native combo/parlay), etc.
  - Event ticker format: KXNFLGAME-YYMONDD<AWAY><HOME> e.g., KXNFLGAME-26SEP20CLETB (CLE at TB Sep 20 2026)
  - Market ticker: KXNFLGAME-26SEP20CLETB-TB (team to win)
  - Binary YES/NO, settle $1 YES, $0 NO
  - Combo markets: KXNFLCOMBO-..., RFQ pricing, same-game and cross-game, limited availability close to event, must all YES to pay $1

## ESPN (NFL metadata only)

- Base: https://site.api.espn.com/apis/site/v2/sports/football/nfl
- Endpoints:
  - /scoreboard?seasonType=2&year=2026&week=1 — schedule, scores, venue, home/away
  - /injuries — injury designations (official nfl.com values mirrored)
- Core venues: https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/venues/{id} — lat/lon for weather
- Note: keyless, no auth, used only for information Kalshi does not provide (home/away, venue indoor flag, scores, injuries). Not a price source.
- Verification: stored verbatim with source_url, fetched_at, logged to manifest via log_external()

## NWS (weather)

- Base: https://api.weather.gov
- Endpoints:
  - /points/{lat},{lon} — gridpoint
  - /points/{lat},{lon}/forecast — forecast
- Note: official US weather service, forward forecasts only, historical unavailable (flagged as forward-only). Weather strategies therefore forward-only by design.

## MasterSite relevant projects

- https://buffedlizard55-lab.github.io/MasterSite/ — directory of verified GitHub Pages projects
- Relevant:
  - NFL Injury Report: https://buffedlizard55-lab.github.io/NFLInjuryReport/ — live injury alerts from free public sources, official nfl.com designations, ESPN timestamps. Use: cross-check injury data.
  - NFLComp: https://buffedlizard55-lab.github.io/NFLComp/ — autonomous NFL betting strategy research & competition, 60 personas, Elo, DVOA, backtest gates. Use: strategy discovery reference, not price source.
  - Commodities: https://buffedlizard55-lab.github.io/Commodities/ — evidence-first paper-trading lab for Kalshi event contracts, hash-chained ledger, execution-realism checks vs trade tape. Use: ledger design reference.
  - Sports Pred, NFL Scoreboard, Weather: similar

## Strategy discovery sources (not price sources)

- Academic: Wolfers & Zitzewitz 2004 on prediction market efficiency, other sports betting efficiency studies
- Reddit: r/sportsbook, r/nfl, r/CFB for strategy concepts (value, contrarian, weather, rest)
- YouTube, X, Facebook, trading communities: conceptual ideas only, documented as discovery-only, never price source

## References for UI design

- https://www.kalshi.com/ — market listing, verification links
- https://www.tradingview.com/the-leap/ — competition leaderboard, portfolio, performance tracking
- https://www.trade-ideas.com/stock-trading-competition/ — competition structure
- https://specials.candlecharts.com/contest/ — contest UI

Goal not to copy, but understand useful competition, leaderboard, portfolio, trade-history, performance-tracking functionality.
