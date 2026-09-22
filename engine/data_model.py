#!/usr/bin/env python3
"""Shared data models (stdlib-only dataclasses/dicts) for the competition.

Design: shared verified market data lives in data/raw/kalshi/ and is NEVER
duplicated per user.  Per-trade records store only references (ticker, snapshot
SHA, timestamp) plus execution fields.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

TradeStatus = Literal[
    "CANDIDATE",      # strategy wants to trade, not yet signaled
    "SIGNAL",         # strategy generated a signal
    "ORDER",          # simulated order placed
    "EXECUTED",       # simulated fill
    "CLOSED",         # position closed (sold)
    "SETTLED",        # market settled, PnL finalized
    "CANCELLED",      # cancelled before execution
    "REJECTED",       # rejected by execution simulator (liquidity, status, etc)
]

Side = Literal["YES", "NO"]

@dataclass
class MarketSnapshot:
    """Verified market data snapshot (stored verbatim in data/raw)."""
    ticker: str
    event_ticker: str
    series_ticker: str
    status: str  # active, open, closed, settled
    title: str
    subtitle: str | None
    yes_bid: float | None
    yes_ask: float | None
    last_price: float | None
    volume: float | None
    volume_24h: float | None
    open_interest: float | None
    liquidity: float | None
    open_time: str | None
    close_time: str | None
    expiration_time: str | None
    result: str | None  # yes/no when settled
    fetched_at: str
    source_url: str
    sha256: str
    orderbook: dict | None = None  # optional live snapshot
    candlesticks: list[dict] | None = None  # optional history

@dataclass
class ParlayLeg:
    """One leg of a parlay/combo."""
    market_ticker: str
    event_ticker: str
    series_ticker: str
    side: Side  # YES means we think market resolves YES
    entry_price: float  # dollars 0.01-0.99
    entry_timestamp: str
    quantity: int
    implied_prob: float
    liquidity_at_entry: float | None
    bid_at_entry: float | None
    ask_at_entry: float | None
    source_file: str  # path to raw snapshot file
    source_sha256: str
    source_url: str
    verification_url: str

@dataclass
class Trade:
    """Immutable-style trade record (hash-chained in ledger)."""
    trade_id: str
    user_id: str
    username: str
    strategy_id: str
    # Trade lifecycle
    status: TradeStatus
    created_at: str
    updated_at: str
    # Parlay structure: 1 leg = single, 2+ legs = parlay
    legs: list[ParlayLeg]
    # Execution fields
    position_size_dollars: float  # total dollars risked
    entry_price_combined: float | None  # for combo: combined price; for single: same as leg price
    exit_price_combined: float | None = None
    exit_timestamp: str | None = None
    settlement_price: float | None = None  # 0 or 1 per leg after settlement
    fees: float = 0.0
    slippage_assumed: float = 0.0
    # PnL
    pnl_dollars: float | None = None
    roi_percent: float | None = None
    result: Literal["WIN", "LOSS", "PENDING", "CANCELLED", "REJECTED"] = "PENDING"
    # Verification
    official_sources: list[str] = field(default_factory=list)
    verification_notes: str = ""
    flags: list[dict] = field(default_factory=list)
    # Hash chain
    prev_hash: str | None = None
    hash: str | None = None
    # Explanation
    why_entered: str = ""
    why_exited: str = ""
    expected_value: float | None = None
    # Market context
    market_type: str = "SYNTHETIC_PARLAY"  # or NATIVE_COMBO or SINGLE
    is_native_kalshi_combo: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Trade":
        legs = [ParlayLeg(**leg) for leg in d.get("legs", [])]
        d2 = {**d, "legs": legs}
        return Trade(**d2)

@dataclass
class User:
    user_id: str
    username: str
    strategy_id: str
    strategy_name: str
    strategy_description: str
    strategy_long_explanation: str  # detailed
    starting_bankroll: float
    current_bankroll: float
    open_trades: list[str] = field(default_factory=list)  # trade_ids
    closed_trades: list[str] = field(default_factory=list)
    total_pnl: float = 0.0
    roi_percent: float = 0.0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_trades: int = 0
    rank: int | None = None
    performance_history: list[dict] = field(default_factory=list)  # equity curve points
    explanation: str = ""
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    last_trade_at: str | None = None
    competition_status: str = "ACTIVE"
    flags: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class Competition:
    competition_id: str
    season: str  # e.g. "2026"
    start_date: str
    end_date: str
    status: str  # UPCOMING, ACTIVE, COMPLETED
    users: list[str]  # user_ids
    total_trades: int = 0
    total_volume: float = 0.0
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    flags: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
