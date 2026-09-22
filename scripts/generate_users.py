#!/usr/bin/env python3
"""Generate users for scalability testing: 5 -> 1000"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.competition import create_users, save_users
import argparse

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100, help="Number of users to generate")
    parser.add_argument("--bankroll", type=float, default=10000.0)
    args = parser.parse_args(argv)
    users = create_users(args.count, args.bankroll)
    save_users(users)
    print(f"Generated {len(users)} users")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
