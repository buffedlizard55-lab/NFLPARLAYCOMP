#!/usr/bin/env python3
"""Append-only, hash-chained ledger for the paper-trading competition.

Every competition event (user creation, candidate, signal, order, fill,
rejection, settlement, explanation, flag, equity snapshot) is one JSON line in
data/competition/ledger.jsonl.  Each record carries:

    seq         — monotonic sequence number
    prev_hash   — SHA-256 of the previous record's canonical JSON
    hash        — SHA-256 of this record's canonical JSON (incl. prev_hash)

Any retroactive edit breaks the chain and is detected by verify_chain().
Records are never updated in place; corrections are appended as new records
that reference the record they supersede.
"""
from __future__ import annotations

import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_PATH = os.path.join(ROOT, "data", "competition", "ledger.jsonl")

GENESIS_HASH = "0" * 64

RECORD_TYPES = {
    "user_created", "candidate", "signal", "order", "fill", "rejection",
    "settlement", "explanation", "flag", "equity_snapshot", "correction",
    "cycle", "note",
}


def canonical(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, path: str = LEDGER_PATH):
        self.path = path
        self.records: list[dict] = []
        self.by_type: dict[str, list[dict]] = {t: [] for t in RECORD_TYPES}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                self.records.append(record)
                self.by_type.setdefault(record.get("type", "?"), []).append(record)

    @property
    def head_hash(self) -> str:
        return self.records[-1]["hash"] if self.records else GENESIS_HASH

    def append(self, rtype: str, payload: dict, at: str, actor: str = "engine") -> dict:
        if rtype not in RECORD_TYPES:
            raise ValueError(f"unknown record type {rtype!r}")
        record = {
            "seq": len(self.records) + 1,
            "type": rtype,
            "at": at,
            "actor": actor,
            "payload": payload,
            "prev_hash": self.head_hash,
        }
        record["hash"] = sha256(canonical(record))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(canonical(record) + "\n")
        self.records.append(record)
        self.by_type.setdefault(rtype, []).append(record)
        return record

    # ---------------------------------------------------------- integrity
    def verify_chain(self) -> dict:
        prev = GENESIS_HASH
        errors = []
        for index, record in enumerate(self.records, start=1):
            if record.get("seq") != index:
                errors.append({"seq_mismatch": index, "found": record.get("seq")})
            if record.get("prev_hash") != prev:
                errors.append({"prev_hash_mismatch": index})
            body = {k: v for k, v in record.items() if k != "hash"}
            if record.get("hash") != sha256(canonical(body)):
                errors.append({"hash_mismatch": index})
            prev = record.get("hash")
        return {"records": len(self.records), "errors": errors,
                "head_hash": prev}

    def rewrite_needed(self) -> bool:
        """True when the on-disk file diverges from memory (tamper check)."""
        if not os.path.exists(self.path):
            return bool(self.records)
        with open(self.path, encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        return len(lines) != len(self.records)
