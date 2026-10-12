#!/usr/bin/env python3
"""
Give pre-existing API keys a public id.

The dashboard revokes a key by key_id. Keys created before that field existed
have none, so they would be listable but not revocable.

key_suffix cannot be backfilled - it is four characters of a plaintext token
that was never stored. Those keys list as "krish_..." with no tail, which is
the honest display.

    python3 scripts/backfill_key_ids.py --dry-run
    python3 scripts/backfill_key_ids.py
"""

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from app.database import api_keys_collection

    if api_keys_collection is None:
        print("MongoDB is not reachable. Start it and re-run.")
        return 1

    missing = list(api_keys_collection.find(
        {"$or": [{"key_id": {"$exists": False}}, {"key_id": ""}]}
    ))

    print(f"Keys without a public id: {len(missing)}")

    for record in missing:
        print(f"  - {record.get('name', 'unnamed')}"
              f" ({record.get('request_count', 0)} requests)")

    if not missing:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        print("\nDry run: would assign a key_id to each.")
        return 0

    for record in missing:
        api_keys_collection.update_one(
            {"_id": record["_id"]},
            {"$set": {"key_id": uuid.uuid4().hex, "revoked_at": record.get("revoked_at")}},
        )

    api_keys_collection.create_index("key_id", unique=True)

    print(f"\nAssigned ids to {len(missing)} key(s). They are now revocable.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
