#!/usr/bin/env python3
"""
Hash-chained immutable trade ledger.

Each trade record includes prev_hash and its own hash = SHA256(prev_hash + canonical_json(trade)).
This creates an append-only chain that can be verified for tampering.

Storage: data/competition/ledger.jsonl (one JSON per line, hash-chained) — the
SINGLE SOURCE OF TRUTH for trade state.  Every state transition (SIGNAL -> ORDER ->
EXECUTED -> SETTLED, or REJECTED) that changes the record is appended as a new
chained entry; ``read_ledger()`` returns raw entries and ``latest_trades()``
collapses them to the newest state per trade_id.

Scalability notes
-----------------
* Append is O(1): the tail of the chain (last hash + next sequence number) is cached
  in memory and initialized with a single scan.  Re-scanning the file on every append
  would be O(n^2) over a 1,000-user cycle.
* Per-trade sidecar files are NOT written during normal operation: they duplicate the
  ledger and would create tens of thousands of redundant files at 1,000 users.  The
  site builder emits bounded, derived drill-down JSON under
  ``site_data/trades/detail/`` only for trades actually shown on the site.
* Verified market data lives in ``data/raw/`` and is referenced by ticker + snapshot
  SHA, never duplicated per trade or per user.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Iterator

from .utils import sha256_hex, sha256_json, iso_now

LEDGER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "competition", "ledger.jsonl")
TRADES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "competition", "trades")


def ensure_dirs() -> None:
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    os.makedirs(TRADES_DIR, exist_ok=True)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


def compute_hash(trade_dict: dict, prev_hash: str | None) -> str:
    """SHA-256 over (prev_hash || canonical JSON of the entry minus its own hash)."""
    copy = {k: v for k, v in trade_dict.items() if k != "hash"}
    payload = (prev_hash or "GENESIS") + canonical_json(copy)
    return sha256_hex(payload.encode())


# ---------------------------------------------------------------- chain tail cache
_TAIL: dict | None = None  # {"hash": str|None, "seq": int, "lines": int}


def _scan_tail(force: bool = False) -> dict:
    """Return {'hash', 'seq', 'lines'} for the current end of the chain.

    Cached for the process lifetime because append_trade is the only mutator here.
    """
    global _TAIL
    if _TAIL is not None and not force:
        return _TAIL
    if not os.path.exists(LEDGER_PATH):
        _TAIL = {"hash": None, "seq": 0, "lines": 0}
        return _TAIL
    last_hash = None
    seq = 0
    lines = 0
    with open(LEDGER_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            lines += 1
            last_hash = entry.get("hash", last_hash)
            entry_seq = entry.get("ledger_seq")
            seq = (int(entry_seq) + 1) if isinstance(entry_seq, int) else lines
    _TAIL = {"hash": last_hash, "seq": seq, "lines": lines}
    return _TAIL


def get_last_hash() -> str | None:
    return _scan_tail()["hash"]


def ledger_length() -> int:
    """Number of chained entries currently in the ledger."""
    return _scan_tail()["lines"]


def append_trade(trade: dict, write_sidecar: bool = False) -> dict:
    """Append a trade state transition to the hash-chained ledger.

    Returns the trade dict with ``prev_hash``, ``ledger_seq`` and ``hash`` set.
    The ledger line is the authoritative record; ``write_sidecar`` is only for
    tools/tests that explicitly want a per-trade file.
    """
    global _TAIL
    tail = _scan_tail()
    entry = dict(trade)
    entry["prev_hash"] = tail["hash"]
    entry["ledger_seq"] = tail["seq"]
    entry["hash"] = compute_hash(entry, tail["hash"])
    with open(LEDGER_PATH, "a", encoding="utf-8") as handle:
        handle.write(canonical_json(entry) + "\n")
    # Advance the cache (module-level, so the next append chains onto THIS entry).
    _TAIL = {"hash": entry["hash"], "seq": tail["seq"] + 1, "lines": tail["lines"] + 1}
    if write_sidecar:
        os.makedirs(TRADES_DIR, exist_ok=True)
        path = os.path.join(TRADES_DIR, f"{trade['trade_id']}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(entry, handle, indent=2, sort_keys=True)
    return entry


def read_ledger() -> List[dict]:
    """Raw chained entries, in append order (may include several per trade)."""
    if not os.path.exists(LEDGER_PATH):
        return []
    out: List[dict] = []
    with open(LEDGER_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def iter_ledger() -> Iterator[dict]:
    """Stream entries without loading the whole chain into memory."""
    if not os.path.exists(LEDGER_PATH):
        return
    with open(LEDGER_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def latest_trades(ledger: List[dict] | None = None) -> List[dict]:
    """Collapse ledger entries to the newest state per trade_id.

    Consumers that want "current state per trade" must use this rather than raw
    ``read_ledger()``, because the ledger keeps the full audit trail.
    """
    rows = ledger if ledger is not None else read_ledger()
    latest: Dict[str, dict] = {}
    for entry in rows:
        tid = entry.get("trade_id")
        if tid:
            latest[tid] = entry
    return list(latest.values())


def verify_chain() -> Dict[str, Any]:
    """Verify hash-chain integrity across every entry."""
    if not os.path.exists(LEDGER_PATH):
        return {"valid": True, "count": 0, "errors": []}
    errors = []
    prev = None
    count = 0
    expected_seq = 0
    with open(LEDGER_PATH, "r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
            except json.JSONDecodeError as error:
                errors.append({"line": idx, "error": f"JSON parse {error}"})
                continue
            count += 1
            if trade.get("prev_hash") != prev:
                errors.append({
                    "line": idx, "trade_id": trade.get("trade_id"),
                    "error": f"prev_hash mismatch: expected {prev}, got {trade.get('prev_hash')}"})
            recomputed = compute_hash(trade, trade.get("prev_hash"))
            if recomputed != trade.get("hash"):
                errors.append({
                    "line": idx, "trade_id": trade.get("trade_id"),
                    "error": f"hash mismatch: expected {recomputed}, got {trade.get('hash')}"})
            seq = trade.get("ledger_seq")
            if seq is not None and seq != expected_seq:
                errors.append({
                    "line": idx, "trade_id": trade.get("trade_id"),
                    "error": f"ledger_seq {seq} out of order (expected {expected_seq})"})
            expected_seq = (seq + 1) if isinstance(seq, int) else expected_seq + 1
            prev = trade.get("hash")
    return {"valid": len(errors) == 0, "count": count, "errors": errors}


def get_trades_by_user(user_id: str, latest_only: bool = True) -> List[dict]:
    rows = read_ledger()
    rows = latest_trades(rows) if latest_only else rows
    return [t for t in rows if t.get("user_id") == user_id]


def get_trades_by_status(status: str, latest_only: bool = True) -> List[dict]:
    rows = read_ledger()
    rows = latest_trades(rows) if latest_only else rows
    return [t for t in rows if t.get("status") == status]


def get_all_trades(latest_only: bool = True) -> List[dict]:
    """All trades. Defaults to newest state per trade_id; pass False for raw chain."""
    rows = read_ledger()
    return latest_trades(rows) if latest_only else rows


def clear_ledger():
    """For testing only."""
    global _TAIL
    ensure_dirs()
    if os.path.exists(LEDGER_PATH):
        os.remove(LEDGER_PATH)
    if os.path.exists(TRADES_DIR):
        for fn in os.listdir(TRADES_DIR):
            fp = os.path.join(TRADES_DIR, fn)
            if os.path.isfile(fp):
                os.remove(fp)
    _TAIL = None
