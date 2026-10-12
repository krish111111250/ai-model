"""
The engine's only piece of state: the API key store.

Documents, chunks, vectors and chat history used to live here. They now live
on the customer's machine (see client_gateway.py), so this module deliberately
declares nothing for them - creating those collections, even empty, would put
the server back in the business of holding customer data.

backend/legacy/ still refers to the old collections. It is reference-only code
and is not imported; restoring it would mean restoring them here too.
"""

import os

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "krish_ai_db")


def get_database():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")

        print(f"\n📡 [KRISH AI] Connected to MongoDB at: {MONGO_URI}")
        print(f"🗄️ [KRISH AI] Key store database: {DB_NAME}")

        return client[DB_NAME]

    except Exception as error:
        print(f"\n❌ CRITICAL: Failed to connect to MongoDB: {error}")
        return None


db = get_database()

api_keys_collection = db["api_keys"] if db is not None else None

# Dashboard accounts. These are people, not documents: the engine still holds
# no customer content, only who may call it.
users_collection = db["users"] if db is not None else None


def initialize_indexes():
    if api_keys_collection is None:
        return

    try:
        # Every authenticated request looks a key up by its hash.
        api_keys_collection.create_index([("key_hash", ASCENDING)], unique=True)
        api_keys_collection.create_index([("tenant_id", ASCENDING)])

        # The dashboard lists a user's keys, so this is the hot path for it.
        api_keys_collection.create_index([("user_id", ASCENDING)])

        if users_collection is not None:
            # Unique at the database level, not just checked in the route: two
            # simultaneous signups with the same address would both pass a
            # read-then-write check.
            users_collection.create_index([("email", ASCENDING)], unique=True)
            users_collection.create_index([("user_id", ASCENDING)], unique=True)

        print("✅ Key store and account store ready (no document collections).")

    except Exception as error:
        print(f"⚠️ MongoDB index initialization warning: {error}")


initialize_indexes()
