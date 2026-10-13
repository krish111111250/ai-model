#!/usr/bin/env python3
"""
Copy each key's owner email onto the key record.

The quota check runs on every authenticated request and needs to know whether
the owner is an admin. Joining to the users collection per request is a read
the hot path does not need, so the email is denormalised onto the key.

Keys without it still work - auth.owner_email() falls back to a lookup and
caches it - this just removes that first lookup.

    python3 scripts/backfill_key_owner_email.py --dry-run
    python3 scripts/backfill_key_owner_email.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from app.database import api_keys_collection, users_collection

    if api_keys_collection is None or users_collection is None:
        print("MongoDB is not reachable. Start it and re-run.")
        return 1

    emails = {
        user["user_id"]: (user.get("email") or "").strip().lower()
        for user in users_collection.find({}, {"user_id": 1, "email": 1})
    }

    missing = list(api_keys_collection.find(
        {"$or": [{"user_email": {"$exists": False}}, {"user_email": ""}]}
    ))

    print(f"Keys without an owner email: {len(missing)}")

    updated = 0

    for record in missing:
        email = emails.get(record.get("user_id", ""), "")

        if not email:
            print(f"  {record.get('name', 'unnamed')}: no account found, skipped")
            continue

        print(f"  {record.get('name', 'unnamed')} -> {email}")

        if not args.dry_run:
            api_keys_collection.update_one(
                {"_id": record["_id"]}, {"$set": {"user_email": email}}
            )
            updated += 1

    if args.dry_run:
        print("\nDry run - nothing changed.")
    else:
        print(f"\nUpdated {updated} key(s).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
