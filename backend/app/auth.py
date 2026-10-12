"""
API key authentication for multi-tenant access.

Each caller gets a key. Everything that key uploads is tagged with its tenant
id, and every retrieval is filtered by that same id, so one tenant can never
read another tenant's documents.

Keys are stored as SHA-256 hashes: a leaked database dump does not hand over
working keys. The plaintext key is shown exactly once, at creation.
"""

import hashlib
import secrets
import uuid
from datetime import datetime

from fastapi import Header, HTTPException

from .database import api_keys_collection

KEY_PREFIX = "krish_"


def hash_key(api_key: str) -> str:
    return hashlib.sha256((api_key or "").encode()).hexdigest()


def generate_api_key(
    name: str = "",
    webhook_url: str = "",
    user_id: str = "",
) -> dict:
    """Create a key. The plaintext is returned here and never stored."""
    if api_keys_collection is None:
        raise HTTPException(status_code=500, detail="MongoDB is not connected.")

    api_key = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key_hash = hash_key(api_key)

    # A tenant is an account, not a key: all of one user's keys share a
    # tenant, so usage and isolation follow the owner. Keys minted without an
    # owner (the CLI, local development) keep the old hash-derived id.
    tenant_id = f"tenant_{user_id}" if user_id else f"tenant_{key_hash[:16]}"

    record = {
        # A public handle for this key. The dashboard revokes by this rather
        # than by key_hash, which is a verifier and has no business travelling
        # in a URL or sitting in a browser history.
        "key_id": uuid.uuid4().hex,
        "key_hash": key_hash,
        # The last four characters, so a user can tell two keys apart in a
        # list. Four of a 43-character random token identifies without
        # meaningfully narrowing a guess.
        "key_suffix": api_key[-4:],
        "tenant_id": tenant_id,
        "user_id": user_id or "",
        "name": name or "unnamed key",
        "webhook_url": webhook_url or "",
        "created_at": datetime.utcnow(),
        "last_used_at": None,
        "revoked": False,
        # Set when the owner revokes it. Soft so that "what was this key doing
        # before we killed it?" stays answerable.
        "revoked_at": None,
        "request_count": 0,
    }

    api_keys_collection.insert_one(record)

    return {
        "api_key": api_key,
        "key_id": record["key_id"],
        "tenant_id": tenant_id,
        "user_id": record["user_id"],
        "name": record["name"],
        "webhook_url": record["webhook_url"],
        "created_at": record["created_at"].isoformat(),
    }


def describe_key(record: dict) -> dict:
    """
    A key as the dashboard may see it.

    There is no plaintext to return even if we wanted to - only a hash was
    ever stored - so this is the whole truth about a key minus its verifier.
    """
    suffix = record.get("key_suffix") or ""

    return {
        "key_id": record.get("key_id", ""),
        "name": record.get("name", "unnamed key"),
        # Keys issued before key_suffix existed have no tail to show.
        "masked": f"{KEY_PREFIX}...{suffix}" if suffix else f"{KEY_PREFIX}...",
        "tenant_id": record.get("tenant_id", ""),
        "created_at": str(record.get("created_at", "")),
        "last_used_at": str(record["last_used_at"]) if record.get("last_used_at") else None,
        "request_count": record.get("request_count", 0),
        "revoked_at": str(record["revoked_at"]) if record.get("revoked_at") else None,
    }


def list_keys_for_user(user_id: str) -> list:
    if api_keys_collection is None or not user_id:
        return []

    records = api_keys_collection.find({"user_id": user_id}).sort("created_at", -1)

    return [describe_key(record) for record in records]


def revoke_key(user_id: str, key_id: str):
    """
    Soft-delete one of this user's keys.

    Scoped by user_id in the query itself, not checked afterwards: an
    ownership test written as a second step is one an edit can drop.
    """
    if api_keys_collection is None:
        raise HTTPException(status_code=500, detail="MongoDB is not connected.")

    record = api_keys_collection.find_one({"key_id": key_id, "user_id": user_id})

    if not record:
        # Deliberately the same answer whether the key belongs to someone else
        # or does not exist: the difference is a key-enumeration oracle.
        raise HTTPException(status_code=404, detail="No such key on this account.")

    if record.get("revoked_at") is not None:
        return describe_key(record)

    api_keys_collection.update_one(
        {"key_id": key_id, "user_id": user_id},
        {"$set": {"revoked_at": datetime.utcnow(), "revoked": True}},
    )

    print(f"🔒 key revoked: {record.get('name', 'unnamed')} ({key_id[:8]})")

    return describe_key(api_keys_collection.find_one({"key_id": key_id}))


def lookup_tenant(api_key: str):
    """Return the tenant record for a key, or None if it is unknown/revoked."""
    if not api_key or api_keys_collection is None:
        return None

    record = api_keys_collection.find_one({"key_hash": hash_key(api_key)})

    if not record:
        return None

    # Two fields because the soft-delete replaced the old boolean: revoked_at
    # carries *when*, which is what makes "what was this key doing before we
    # killed it?" answerable. The boolean is still honoured so that keys
    # created before the change keep working the way they did.
    if record.get("revoked_at") is not None or record.get("revoked"):
        return None

    return record


def touch_key(key_hash: str):
    if api_keys_collection is None:
        return

    try:
        api_keys_collection.update_one(
            {"key_hash": key_hash},
            {
                "$set": {"last_used_at": datetime.utcnow()},
                "$inc": {"request_count": 1},
            }
        )
    except Exception as e:
        print(f"⚠️ Could not record key usage: {e}")


async def require_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> dict:
    """FastAPI dependency: rejects the request unless X-API-Key is valid."""
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header.",
        )

    tenant = lookup_tenant(x_api_key)

    if not tenant:
        raise HTTPException(
            status_code=403,
            detail="Invalid or revoked API key.",
        )

    touch_key(tenant["key_hash"])
    return tenant


async def optional_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """
    Same, but allows anonymous use.

    The bundled React app talks to this backend without a key; those requests
    stay on the local tenant and never see API-key tenants' documents.
    """
    if not x_api_key:
        return None

    tenant = lookup_tenant(x_api_key)

    if not tenant:
        raise HTTPException(status_code=403, detail="Invalid or revoked API key.")

    touch_key(tenant["key_hash"])
    return tenant
