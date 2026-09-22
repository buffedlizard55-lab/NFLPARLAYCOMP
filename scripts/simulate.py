#!/usr/bin/env python3
"""CLI wrapper for competition runner."""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.competition import run_competition_cycle

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run NFL parlay competition cycle")
    parser.add_argument("--users", type=int, default=None, help="Number of users (5..1000). If omitted, uses existing.")
    parser.add_argument("--trades-per-user", type=int, default=3)
    parser.add_argument("--bankroll", type=float, default=10000.0)
    parser.add_argument("--clear", action="store_true", help="Clear ledger and users first")
    args = parser.parse_args(argv)

    result = run_competition_cycle(
        num_users=args.users,
        max_trades_per_user=args.trades_per_user,
        starting_bankroll=args.bankroll,
        clear=args.clear,
    )
    import json
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
