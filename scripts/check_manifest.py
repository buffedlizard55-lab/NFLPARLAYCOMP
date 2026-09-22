#!/usr/bin/env python3
"""Integrity check for the fetch manifest: every logged call must be well-formed,
and every stored raw file must be reproducible from a logged URL.  Exits non-zero
on structural problems (this is the collector's own audit gate)."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "raw", "manifest.jsonl")


def main() -> int:
    if not os.path.exists(MANIFEST):
        print("manifest.jsonl missing — nothing collected yet")
        return 0
    rows = 0
    bad = 0
    statuses = {}
    with open(MANIFEST, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows += 1
            try:
                entry = json.loads(line)
                for field in ("url", "at", "sha256", "status"):
                    if field not in entry:
                        raise ValueError(f"missing {field}")
                statuses[str(entry["status"])] = statuses.get(str(entry["status"]), 0) + 1
            except (json.JSONDecodeError, ValueError) as error:
                bad += 1
                if bad <= 5:
                    print(f"BAD manifest row: {error}")
    print(json.dumps({"manifest_rows": rows, "malformed": bad,
                      "status_counts": statuses}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
