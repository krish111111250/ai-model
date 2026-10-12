#!/usr/bin/env python3
"""
Give the existing API keys an owner.

Keys were created before accounts existed, so their user_id is empty and the
dashboard cannot list them. This assigns them to one account.

Assign rather than drop by default: one of these keys is in use by the local
gateway (~/.krish/config.json), and dropping it silently breaks the running
app. --drop is there for when you would rather start clean.

    python3 scripts/migrate_api_keys_to_users.py --email you@example.com --dry-run
    python3 scripts/migrate_api_keys_to_users.py --email you@example.com
    python3 scripts/migrate_api_keys_to_users.py --drop          # delete orphans
"""

import argparse
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", help="account to assign the keys to")
    parser.add_argument("--password", help="password if the account must be created")
    parser.add_argument("--drop", action="store_true",
                        help="delete ownerless keys instead of assigning them")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.drop and not args.email:
        parser.error("--email is required unless you pass --drop")

    from app.accounts import hash_password, normalize_email
    from app.database import api_keys_collection, users_collection

    if api_keys_collection is None or users_collection is None:
        print("MongoDB is not reachable. Start it and re-run.")
        return 1

    # An empty user_id and a missing field both mean "no owner".
    orphans = list(api_keys_collection.find(
        {"$or": [{"user_id": {"$exists": False}}, {"user_id": ""}]}
    ))

    print(f"API keys without an owner: {len(orphans)}")

    for key in orphans:
        print(f"  - {key.get('name', 'unnamed')} "
              f"(tenant {key.get('tenant_id', '?')}, "
              f"{key.get('request_count', 0)} requests)")

    if not orphans:
        print("Nothing to migrate.")
        return 0

    if args.drop:
        if args.dry_run:
            print(f"\nDry run: would delete {len(orphans)} key(s).")
            return 0

        result = api_keys_collection.delete_many(
            {"_id": {"$in": [key["_id"] for key in orphans]}}
        )
        print(f"\nDeleted {result.deleted_count} key(s). "
              "Any client still using one will now get 403.")
        return 0

    email = normalize_email(args.email)
    user = users_collection.find_one({"email": email})

    if user:
        print(f"\nOwner: {email} (existing account {user['user_id']})")
    else:
        password = args.password or secrets.token_urlsafe(12)

        print(f"\nOwner: {email} (new account)")

        if not args.password:
            print(f"  generated password: {password}")
            print("  change it after signing in")

        if args.dry_run:
            print("\nDry run: would create the account and assign the keys.")
            return 0

        import uuid

        user = {
            "user_id": uuid.uuid4().hex,
            "email": email,
            "hashed_password": hash_password(password),
            "created_at": datetime.now(timezone.utc),
            "last_login_at": None,
        }
        users_collection.insert_one(dict(user))

    if args.dry_run:
        print(f"\nDry run: would assign {len(orphans)} key(s) to {email}.")
        return 0

    # tenant_id is left alone on purpose. Rewriting it would change the label
    # that past request logs were written under, for no gain while the engine
    # stores nothing per tenant.
    result = api_keys_collection.update_many(
        {"_id": {"$in": [key["_id"] for key in orphans]}},
        {"$set": {"user_id": user["user_id"], "revoked_at": None}},
    )

    print(f"\nAssigned {result.modified_count} key(s) to {email}.")
    print("They now appear under that account in the dashboard.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
