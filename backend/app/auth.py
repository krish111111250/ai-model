"""
API key authentication for multi-tenant access.

Each caller gets a key. Everything that key uploads is tagged with its tenant
id, and every retrieval is filtered by that same id, so one tenant can never
read another tenant's documents.

Keys are stored as SHA-256 hashes: a leaked database dump does not hand over
working keys. The plaintext key is shown exactly once, at creation.
"""

import hashlib
import os
import secrets
import uuid
from datetime import datetime

from fastapi import Header, HTTPException

from .database import api_keys_collection

KEY_PREFIX = "krish_"

# Accounts that are never metered. Checked against the live list on every
# request rather than stamped onto the key at creation, so adding or removing
# an admin takes effect immediately instead of only for new keys.
ADMIN_EMAILS = {"ramanikrish133@gmail.com", "founder@krish.ai"}

# What the landing page advertises for the free tier.
FREE_MONTHLY_QUOTA = int(os.getenv("FREE_MONTHLY_QUOTA", "100"))


def current_period() -> str:
    """The quota window, as "2026-10"."""
    now = datetime.utcnow()

    return f"{now.year:04d}-{now.month:02d}"


def owner_email(record: dict) -> str:
    """
    The email of the account that owns this key.

    Denormalised onto the key record at creation, because this is read on
    every authenticated request and a join per request to answer "is this an
    admin" is a read the hot path does not need. Keys issued before the field
    existed fall back to one lookup, cached for the life of the process.
    """
    email = (record.get("user_email") or "").strip().lower()

    if email:
        return email

    user_id = record.get("user_id") or ""

    if not user_id:
        return ""

    if user_id not in _email_cache:
        from .database import users_collection

        user = (
            users_collection.find_one({"user_id": user_id}, {"email": 1})
            if users_collection is not None
            else None
        )

        _email_cache[user_id] = (user or {}).get("email", "").strip().lower()

    return _email_cache[user_id]


_email_cache = {}


def is_admin(record: dict) -> bool:
    return owner_email(record) in ADMIN_EMAILS


def quota_used(record: dict) -> int:
    """
    Requests this key has made in the current month.

    Not request_count: that one counts for the lifetime of the key and nothing
    resets it, so metering against it would be a lifetime cap wearing a
    monthly label - and the keys already in this database are past 400.
    """
    if record.get("quota_period") != current_period():
        return 0

    return int(record.get("quota_count") or 0)


def enforce_quota(record: dict):
    """Let admins through; meter everyone else against the month."""
    if is_admin(record):
        return

    used = quota_used(record)

    if used >= FREE_MONTHLY_QUOTA:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly quota exceeded ({used}/{FREE_MONTHLY_QUOTA}). "
                "Please upgrade your plan."
            ),
        )


def hash_key(api_key: str) -> str:
    return hashlib.sha256((api_key or "").encode()).hexdigest()


def generate_api_key(
    name: str = "",
    webhook_url: str = "",
    user_id: str = "",
    user_email: str = "",
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
        # Denormalised so the quota check needs no join - see owner_email().
        "user_email": (user_email or "").strip().lower(),
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
        # This month's usage, not the lifetime total below it. Zero for a key
        # whose counter belongs to a previous month.
        "quota_used": quota_used(record),
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


def touch_key(record: dict):
    """
    Record one use: lifetime total, and the current month's count.

    The month's counter is reset rather than incremented when the period has
    rolled over, which is what makes the quota monthly. Same single write as
    before - the roll is a $set in the same update.
    """
    if api_keys_collection is None:
        return

    period = current_period()

    update = {
        "$set": {"last_used_at": datetime.utcnow()},
        "$inc": {"request_count": 1},
    }

    if record.get("quota_period") == period:
        update["$inc"]["quota_count"] = 1
    else:
        update["$set"]["quota_period"] = period
        update["$set"]["quota_count"] = 1

    try:
        api_keys_collection.update_one({"key_hash": record["key_hash"]}, update)
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

    # Decided on the record already in hand: no second read, and no write for
    # a request that is about to be rejected.
    enforce_quota(tenant)

    touch_key(tenant)
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

    enforce_quota(tenant)
    touch_key(tenant)
    return tenant
