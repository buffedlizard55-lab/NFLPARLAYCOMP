# Strategy Research

## Discovery Process

Research → Retrieve → Verify → Store → Calculate → Simulate → Record → Display → Provide source

### Sources for strategy discovery (not price sources)

- Academic: Wolfers & Zitzewitz (2004) on prediction market efficiency, studies on home field advantage, rest advantage, weather impact
- NFL data: ESPN scoreboard, injuries, team stats, venues
- Public analysis: Reddit r/sportsbook, r/nfl, r/fantasyfootball, sports communities, trading communities
- YouTube, X, Facebook: conceptual ideas, e.g., weather under, injury fade, contrarian public
- Existing projects: NFLComp (60 personas), Commodities (23 personas), MLBComp

Each discovered strategy documented with source and independently tested forward.

## Strategy Categories

### Market-based

- Implied Value: model prob vs market prob edge >5%
- Line Movement Momentum: follow 5c+ moves in 2h with volume spike
- Mean Reversion: fade >8c moves without news
- Cross-Market Arb: moneyline vs spread vs total misalignment >8%
- Liquidity Provision: market making when spread >8c
- Contrarian Public: fade >70% public side
- Alt Line Value: alt spread mispriced vs main

### Game-based

- Home Field Momentum: home team >65% home win last 8
- Rest Advantage: +3 rest days differential
- Divisional Dog: divisional underdogs +3 to +7 cover 53%+
- Primetime Favorite Fade: primetime favorites >7.5 cover 42%
- Coaching Mismatch: top 5 vs bottom 5 coaching
- Veteran QB Spread Cover: veteran QB 10+ years as underdog
- Blowout Reversion: team lost by 20+ last week bounces back ATS 55%

### Situational

- Bad Weather Under: wind >20mph or temp <25F, under hits 57%
- Injury Fade: QB1 OUT and market moved <3c
- Short Week Under: TNF under due to short prep, 54% under
- Rookie QB Under: rookie first 3 starts under 57%
- Q1 Under: divisional games start slow
- TNF Home Dog: TNF home dogs +2 to +6 cover 56%
- Indoor Over: indoor games over when total <48, 53%
- 2H Comeback: team down 1-7 at half but strong 2H team

### Correlation (parlay-specific)

- Spread + Moneyline: favorite spread cover + moneyline win, correlation 0.85, flagged
- Total + Underdog: defensive underdog + under, correlation 0.6
- 1H vs Full Game Divergence: >10% divergence reverts 60%
- TD + Game: anytime TD + team win correlation 0.65
- Team Total Over/Under: offensive efficiency vs defensive

### Statistical

- Elo Model: Elo rating vs market, 55% vs closing
- DVOA Value: DVOA top 5 vs bottom 5, 62% win
- Win Streak Fade: fade 4+ win streak teams when moneyline >70%
- 3-Game Momentum: ATS streak continues 54%

## Evidence Standards

- Never assume strategy works because someone claims it works
- Document source, independently test forward
- Flag if historical data unavailable (e.g., weather forward-only)
- Provide win rates, sample sizes, time periods

## Parlay Construction Research

- Native Kalshi combos: RFQ pricing, same-game more common, limited availability close to event, priced by market makers, not orderbook
- Synthetic parlays: product pricing assumes independence, but correlation exists (e.g., spread + moneyline highly correlated). Must flag correlation and discount.
- Fees compound per leg for synthetic, but native combo fee is single.
- Slippage and liquidity: synthetic requires liquidity in each leg, combo requires liquidity in combo market only (often lower).

## Future Research

- More player prop markets (anytime TD, first TD) as they become liquid
- Weather model improvement with historical NWS archive (if available)
- Injury model with official NFL injury report timestamps
- Integration with NFL Injury Report project for real-time alerts
- Backtesting over full 2026 season once data collected
