#!/usr/bin/env python3
"""
Purge legacy document state from the server.

The server is now a stateless answer engine: documents live on customers'
machines. This removes what the old stateful architecture left behind:

  - backend/app/chroma_db/   the server-side vector store
  - app/chroma_db/           a stray copy from running uvicorn at the repo root
  - MongoDB: documents, chunks, vectors, chat_sessions

API keys are kept - they are how callers authenticate, not customer data.

    python3 scripts/purge_server_state.py --dry-run   # show what would go
    python3 scripts/purge_server_state.py             # do it
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Both locations exist: the server wrote a relative path, so where it landed
# depended on the working directory uvicorn was started from.
CHROMA_PATHS = [
    ROOT / "backend" / "app" / "chroma_db",
    ROOT / "app" / "chroma_db",
]

# Collections that held customer document content.
DOCUMENT_COLLECTIONS = ["documents", "chunks", "vectors", "chat_sessions", "jobs"]

# Collections the stateless engine still needs.
KEEP_COLLECTIONS = ["api_keys"]


def folder_size(path: Path) -> str:
    if not path.exists():
        return "0 B"

    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024:
            return f"{total:.1f} {unit}"
        total /= 1024

    return f"{total:.1f} TB"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="show what would be removed")
    parser.add_argument("--mongo-uri", default="mongodb://localhost:27017/")
    parser.add_argument("--db-name", default="krish_ai_db")
    args = parser.parse_args()

    print("Server state purge\n")

    # 1. The server-side vector stores
    for chroma_path in CHROMA_PATHS:
        print(f"ChromaDB folder: {chroma_path}")

        if not chroma_path.exists():
            print("  not present - nothing to do")
            continue

        print(f"  size: {folder_size(chroma_path)}")

        if args.dry_run:
            print("  would delete")
        else:
            shutil.rmtree(chroma_path)
            print("  deleted ✅")

    # 2. Document rows in MongoDB
    try:
        from pymongo import MongoClient

        client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[args.db_name]
    except Exception as e:
        print(f"\nMongoDB not reachable ({e}).")
        print("Start it and re-run, or the document rows will remain.")
        return 1

    print(f"\nMongoDB: {args.db_name}")

    for name in DOCUMENT_COLLECTIONS:
        count = db[name].count_documents({})

        if not count:
            print(f"  {name}: empty")
            continue

        if args.dry_run:
            print(f"  {name}: {count} rows would be deleted")
        else:
            db[name].drop()
            print(f"  {name}: {count} rows deleted ✅")

    for name in KEEP_COLLECTIONS:
        print(f"  {name}: {db[name].count_documents({})} rows KEPT (authentication)")

    if args.dry_run:
        print("\nDry run - nothing changed. Re-run without --dry-run to apply.")
    else:
        print("\nServer is now stateless: no customer documents, no vectors, no chat history.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
