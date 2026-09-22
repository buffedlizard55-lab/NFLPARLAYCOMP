#!/usr/bin/env python3
"""
Hash-chained immutable trade ledger.

Each trade record includes prev_hash and its own hash = SHA256(prev_hash + canonical_json(trade)).
This creates an append-only chain that can be verified for tampering.

Storage: data/competition/ledger.jsonl (one JSON per line, hash-chained)
Also: data/competition/trades/<trade_id>.json (full record)

The ledger reuses verified market data from data/raw/ (never duplicated per trade).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Iterator

from .utils import sha256_hex, sha256_json, iso_now

LEDGER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "competition", "ledger.jsonl")
TRADES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "competition", "trades")

def ensure_dirs():
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    os.makedirs(TRADES_DIR, exist_ok=True)

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)

def compute_hash(trade_dict: dict, prev_hash: str | None) -> str:
    # Exclude hash field itself from calculation
    copy = {k: v for k, v in trade_dict.items() if k != "hash"}
    payload = (prev_hash or "GENESIS") + canonical_json(copy)
    return sha256_hex(payload.encode())

def get_last_hash() -> str | None:
    if not os.path.exists(LEDGER_PATH):
        return None
    last = None
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                last = entry.get("hash")
            except:
                continue
    return last

def append_trade(trade: dict) -> dict:
    """Append a trade to the hash-chained ledger."""
    ensure_dirs()
    prev_hash = get_last_hash()
    trade["prev_hash"] = prev_hash
    trade["hash"] = compute_hash(trade, prev_hash)
    # Write to ledger.jsonl
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(canonical_json(trade) + "\n")
    # Write full record to trades/<id>.json
    trade_path = os.path.join(TRADES_DIR, f"{trade['trade_id']}.json")
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump(trade, f, indent=2, sort_keys=True)
    return trade

def read_ledger() -> List[dict]:
    if not os.path.exists(LEDGER_PATH):
        return []
    out = []
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except:
                continue
    return out

def verify_chain() -> Dict[str, Any]:
    """Verify hash chain integrity."""
    if not os.path.exists(LEDGER_PATH):
        return {"valid": True, "count": 0, "errors": []}
    errors = []
    prev = None
    count = 0
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line=line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
            except Exception as e:
                errors.append({"line": idx, "error": f"JSON parse {e}"})
                continue
            count += 1
            expected_prev = prev
            actual_prev = trade.get("prev_hash")
            if expected_prev != actual_prev:
                errors.append({"line": idx, "trade_id": trade.get("trade_id"), "error": f"prev_hash mismatch expected {expected_prev} got {actual_prev}"})
            # Recompute hash
            recomputed = compute_hash(trade, actual_prev)
            if recomputed != trade.get("hash"):
                errors.append({"line": idx, "trade_id": trade.get("trade_id"), "error": f"hash mismatch expected {recomputed} got {trade.get('hash')}"})
            prev = trade.get("hash")
    return {"valid": len(errors) == 0, "count": count, "errors": errors}

def get_trades_by_user(user_id: str) -> List[dict]:
    return [t for t in read_ledger() if t.get("user_id") == user_id]

def get_trades_by_status(status: str) -> List[dict]:
    return [t for t in read_ledger() if t.get("status") == status]

def get_all_trades() -> List[dict]:
    return read_ledger()

def clear_ledger():
    """For testing only."""
    ensure_dirs()
    if os.path.exists(LEDGER_PATH):
        os.remove(LEDGER_PATH)
    if os.path.exists(TRADES_DIR):
        for fn in os.listdir(TRADES_DIR):
            fp = os.path.join(TRADES_DIR, fn)
            if os.path.isfile(fp):
                os.remove(fp)
