#!/usr/bin/env python3
"""
Verification module: audit ledger, data integrity, trade verifiability.

Checks:
- Hash chain integrity
- Every trade references existing market data
- Prices within valid bounds
- Timestamps valid
- Settlement consistency
- Flags for missing/unverified data
- Manifest integrity
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

from .ledger import verify_chain, read_ledger
from .utils import make_flag, safe_float, iso_now

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
COMP = os.path.join(ROOT, "data", "competition")
MANIFEST = os.path.join(RAW, "manifest.jsonl")

def verify_manifest() -> dict:
    if not os.path.exists(MANIFEST):
        return {"exists": False, "rows": 0, "malformed": 0, "flags": [make_flag("MISSING_DATA", "manifest.jsonl missing", severity="medium")]}
    rows = 0
    bad = 0
    statuses = {}
    with open(MANIFEST, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line:
                continue
            rows += 1
            try:
                entry = json.loads(line)
                for field in ("url", "at", "sha256", "status"):
                    if field not in entry:
                        raise ValueError(f"missing {field}")
                statuses[str(entry["status"])] = statuses.get(str(entry["status"]), 0) + 1
            except:
                bad += 1
    return {"exists": True, "rows": rows, "malformed": bad, "status_counts": statuses, "valid": bad == 0}

def verify_trades() -> dict:
    trades = read_ledger()
    errors = []
    flags = []
    suspicious_prices = 0
    missing_timestamps = 0
    seen_hashes = set()
    seen_trade_status = set()

    for trade in trades:
        tid = trade.get("trade_id")
        status = trade.get("status")
        h = trade.get("hash")
        # Duplicate hash is real error (exact duplicate line)
        if h in seen_hashes:
            errors.append({"trade_id": tid, "error": "duplicate hash (exact duplicate ledger line)"})
            flags.append(make_flag("DUPLICATE_TRADE", f"Duplicate hash {h[:12]} for {tid}", trade_id=tid, severity="high"))
        seen_hashes.add(h)
        # Same trade_id + same status appearing twice is suspicious (should be state transition)
        key = (tid, status)
        if key in seen_trade_status:
            # Allow if it's a re-run? Flag as low severity, not error, for lifecycle tracking
            flags.append(make_flag("DUPLICATE_TRADE", f"Duplicate trade_id+status {tid} {status} (may be re-run)", trade_id=tid, severity="low"))
        seen_trade_status.add(key)

        # Price checks
        for leg in trade.get("legs", []):
            price = safe_float(leg.get("entry_price"))
            if price is None or not (0.01 <= price <= 0.99):
                suspicious_prices += 1
                flags.append(make_flag("SUSPICIOUS_PRICE", f"Price {price} out of bounds for {leg.get('market_ticker')}", trade_id=tid, market_ticker=leg.get("market_ticker"), severity="high"))
            # Timestamp
            if not leg.get("entry_timestamp"):
                missing_timestamps += 1
                flags.append(make_flag("MISSING_TIMESTAMP", f"Missing timestamp for {leg.get('market_ticker')}", trade_id=tid, severity="medium"))

        # Check market references exist in raw data
        for leg in trade.get("legs", []):
            event_ticker = leg.get("event_ticker")
            if event_ticker:
                market_file = os.path.join(RAW, "kalshi", "markets", f"{event_ticker}.json")
                if not os.path.exists(market_file):
                    # Not necessarily error if using synthetic fixture
                    flags.append(make_flag("UNVERIFIED_DATA", f"Market file missing for {event_ticker}, may be synthetic fixture", trade_id=tid, severity="low"))

        # PnL calc check
        if trade.get("status") == "SETTLED":
            pnl = trade.get("pnl_dollars")
            if pnl is None:
                errors.append({"trade_id": tid, "error": "SETTLED trade missing PnL"})
            # ROI check
            roi = trade.get("roi_percent")
            if roi is None:
                flags.append(make_flag("CALCULATION_ERROR", f"Missing ROI for settled trade {tid}", trade_id=tid, severity="low"))

    return {
        "total_trades": len(trades),
        "errors": errors,
        "flags": flags,
        "suspicious_prices": suspicious_prices,
        "missing_timestamps": missing_timestamps,
        "duplicate_count": len([e for e in errors if "duplicate hash" in e.get("error","")]),
    }

def verify_users() -> dict:
    users_path = os.path.join(COMP, "users.json")
    if not os.path.exists(users_path):
        return {"exists": False, "count": 0}
    with open(users_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        users = data.get("users", [])
    errors = []
    for u in users:
        if not u.get("username"):
            errors.append({"user_id": u.get("user_id"), "error": "missing username"})
        if u.get("starting_bankroll", 0) <= 0:
            errors.append({"user_id": u.get("user_id"), "error": "invalid bankroll"})
        # Check rank consistency
        if u.get("rank") is None:
            errors.append({"user_id": u.get("user_id"), "error": "missing rank"})
    return {"exists": True, "count": len(users), "errors": errors}

def full_verification() -> dict:
    chain = verify_chain()
    manifest = verify_manifest()
    trades = verify_trades()
    users = verify_users()

    all_flags = []
    all_flags.extend(trades.get("flags", []))
    if not manifest.get("valid", True):
        all_flags.append(make_flag("API_ERROR", "Manifest has malformed rows", severity="high"))
    if not chain.get("valid"):
        all_flags.append(make_flag("CALCULATION_ERROR", f"Hash chain invalid: {chain.get('errors')}", severity="high"))

    return {
        "timestamp": iso_now(),
        "chain": chain,
        "manifest": manifest,
        "trades": trades,
        "users": users,
        "flags": all_flags,
        "valid": chain.get("valid") and manifest.get("valid", True) and len(trades.get("errors", [])) == 0,
    }

def main() -> int:
    result = full_verification()
    print(json.dumps(result, indent=2))
    # Write to verification report
    report_path = os.path.join(COMP, "verification_report.json")
    os.makedirs(COMP, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return 0 if result["valid"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
