#!/usr/bin/env python3
"""
Give every existing account an explicit plan.

A missing plan already reads as free, so this changes no behaviour. It makes
the field present on every document, which is what lets a query filter or
index on it without special-casing absence.

    python3 scripts/backfill_user_plans.py --dry-run
    python3 scripts/backfill_user_plans.py
    python3 scripts/backfill_user_plans.py --email you@example.com --plan pro
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--email", help="set one account's plan instead")
    parser.add_argument("--plan", default="free", help="free or pro")
    args = parser.parse_args()

    from app.auth import DEFAULT_PLAN, UNLIMITED_PLANS
    from app.database import users_collection

    if users_collection is None:
        print("MongoDB is not reachable. Start it and re-run.")
        return 1

    known = {DEFAULT_PLAN} | set(UNLIMITED_PLANS)

    if args.plan not in known:
        print(f"Unknown plan {args.plan!r}. Known: {sorted(known)}")
        return 1

    if args.email:
        email = args.email.strip().lower()
        user = users_collection.find_one({"email": email}, {"plan": 1})

        if not user:
            print(f"No account for {email}.")
            return 1

        print(f"{email}: {user.get('plan') or '(none)'} -> {args.plan}")

        if not args.dry_run:
            users_collection.update_one(
                {"email": email}, {"$set": {"plan": args.plan}}
            )
            print("  updated")
        else:
            print("  dry run - nothing changed")

        return 0

    missing = list(users_collection.find(
        {"$or": [{"plan": {"$exists": False}}, {"plan": ""}]}, {"email": 1}
    ))

    print(f"Accounts without an explicit plan: {len(missing)}")

    for user in missing:
        print(f"  {user.get('email', '?')} -> {DEFAULT_PLAN}")

    if not missing:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        print("\nDry run - nothing changed.")
        return 0

    result = users_collection.update_many(
        {"$or": [{"plan": {"$exists": False}}, {"plan": ""}]},
        {"$set": {"plan": DEFAULT_PLAN}},
    )

    print(f"\nUpdated {result.modified_count} account(s).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
