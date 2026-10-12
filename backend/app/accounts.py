"""
Cloud account identity: users, passwords and session tokens.

Deliberately separate from app/auth.py. That module authenticates *machines*
calling the engine with a long-lived API key; this one authenticates *people*
using the dashboard with a short-lived session. Different lifetimes, different
revocation stories, so they do not share code.

Nothing here touches documents. An account exists to own API keys and a bill.
"""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Header, HTTPException

from .database import users_collection

JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "72"))

# bcrypt refuses anything longer and will not truncate for us, which is the
# right call: two different long passwords must never collide.
BCRYPT_MAX_BYTES = 72
MIN_PASSWORD_LENGTH = 8

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Verified against when no such user exists, so a wrong address and a wrong
# password take the same time to fail. Without it, response timing tells an
# attacker which addresses are registered.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt())


def jwt_secret() -> str:
    """
    The signing key, or a refusal.

    No default and no generated fallback: a default would be public, and a
    per-process random key would invalidate every session on restart while
    looking like it worked.
    """
    secret = os.getenv("JWT_SECRET", "").strip()

    if not secret:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET is not set on the server. Accounts are disabled.",
        )

    return secret


# -----------------------------
# PASSWORDS
# -----------------------------
def hash_password(password: str) -> str:
    password = password or ""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )

    encoded = password.encode("utf-8")

    if len(encoded) > BCRYPT_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at most {BCRYPT_MAX_BYTES} bytes.",
        )

    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            (password or "").encode("utf-8"), (hashed or "").encode("utf-8")
        )
    except (ValueError, TypeError):
        # An over-long password or a malformed stored hash is a failed login,
        # not a 500.
        return False


# -----------------------------
# USERS
# -----------------------------
def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()

    if not EMAIL_PATTERN.match(email):
        raise HTTPException(status_code=400, detail="A valid email is required.")

    return email


def public_user(user: dict) -> dict:
    """The fields safe to return. The hash never leaves this module."""
    return {
        "user_id": user.get("user_id", ""),
        "email": user.get("email", ""),
        "created_at": str(user.get("created_at", "")),
    }


def create_user(email: str, password: str) -> dict:
    if users_collection is None:
        raise HTTPException(status_code=503, detail="Account store unavailable.")

    email = normalize_email(email)

    # Hash before the insert so a weak password fails before a row exists.
    hashed = hash_password(password)

    user = {
        "user_id": uuid.uuid4().hex,
        "email": email,
        "hashed_password": hashed,
        "auth_provider": "password",
        "created_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }

    from pymongo.errors import DuplicateKeyError

    try:
        users_collection.insert_one(dict(user))
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="That email is already registered.")

    print(f"👤 account created: {email}")

    return user


def authenticate(email: str, password: str):
    """The user, or None. Same work either way - see _DUMMY_HASH."""
    if users_collection is None:
        raise HTTPException(status_code=503, detail="Account store unavailable.")

    user = users_collection.find_one({"email": (email or "").strip().lower()})

    if not user:
        verify_password(password, _DUMMY_HASH.decode("utf-8"))
        return None

    if not user.get("hashed_password"):
        # Signed up through a provider, so there is no password to check. Say
        # which provider rather than "wrong password" for an account that
        # never had one.
        provider = user.get("auth_provider", "a provider")
        raise HTTPException(
            status_code=400,
            detail=f"This account signs in with {provider}. Use that button instead.",
        )

    if not verify_password(password, user.get("hashed_password", "")):
        return None

    users_collection.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"last_login_at": datetime.now(timezone.utc)}},
    )

    return user


def find_or_create_oauth_user(
    email: str,
    provider: str,
    provider_id: str,
    email_verified: bool,
) -> dict:
    """
    The account behind a provider sign-in, creating it if new.

    An existing account with the same address is only linked when the provider
    says the address is verified. Linking on an unverified email is an account
    takeover: anyone who can set that address on their provider profile would
    inherit the account and its API keys.
    """
    if users_collection is None:
        raise HTTPException(status_code=503, detail="Account store unavailable.")

    email = normalize_email(email)
    existing = users_collection.find_one({"email": email})

    if existing:
        if not email_verified and existing.get("auth_provider") != provider:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"An account already uses {email}, and {provider} has not "
                    "verified that address. Sign in with your password instead."
                ),
            )

        users_collection.update_one(
            {"user_id": existing["user_id"]},
            {"$set": {
                "last_login_at": datetime.now(timezone.utc),
                f"providers.{provider}": provider_id,
            }},
        )

        return existing

    user = {
        "user_id": uuid.uuid4().hex,
        "email": email,
        # No password: this account can only ever sign in through a provider
        # until it sets one.
        "hashed_password": "",
        "auth_provider": provider,
        "providers": {provider: provider_id},
        "created_at": datetime.now(timezone.utc),
        "last_login_at": datetime.now(timezone.utc),
    }

    from pymongo.errors import DuplicateKeyError

    try:
        users_collection.insert_one(dict(user))
    except DuplicateKeyError:
        # Two callbacks raced; the other one won.
        return users_collection.find_one({"email": email})

    print(f"👤 account created via {provider}: {email}")

    return user


# -----------------------------
# SESSION TOKENS
# -----------------------------
def create_access_token(user: dict) -> dict:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=JWT_TTL_HOURS)

    payload = {
        "sub": user["user_id"],
        "email": user["email"],
        "iat": now,
        "exp": expires,
    }

    token = jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires.isoformat(),
    }


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token.")


async def get_current_user(authorization: str = Header(None)) -> dict:
    """
    FastAPI dependency for the dashboard routes.

    The token proves who signed in; the user is then re-read from the database
    so that a deleted account cannot keep working until its token expires.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing session token. Send 'Authorization: Bearer <token>'.",
        )

    payload = decode_token(authorization.split(" ", 1)[1].strip())

    if users_collection is None:
        raise HTTPException(status_code=503, detail="Account store unavailable.")

    user = users_collection.find_one({"user_id": payload.get("sub", "")})

    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists.")

    return user
