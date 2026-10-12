"""
Sign in with GitHub or Google.

Hand-rolled on httpx rather than pulled in through authlib: the two flows are
about sixty lines, and the parts worth getting right - the state check, the
email-verification rule before linking an account - are the parts a library
would hide.

Nothing is stored for a flow in progress. The state parameter is a short-lived
signed token, so there is no pending-login table to clean up and a restart
mid-flow costs the user one retry instead of a confusing failure.
"""

import os
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .accounts import (
    JWT_ALGORITHM,
    create_access_token,
    find_or_create_oauth_user,
    jwt_secret,
)
from .rate_limit import limiter

router = APIRouter(prefix="/v1/auth", tags=["oauth"])

# A flow must finish inside this window. Long enough to read a consent screen,
# short enough that a leaked callback URL is useless by the time it is found.
STATE_TTL_SECONDS = 600

PROVIDERS = {
    "github": {
        "label": "GitHub",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
        "id_env": "GITHUB_CLIENT_ID",
        "secret_env": "GITHUB_CLIENT_SECRET",
    },
    "google": {
        "label": "Google",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
        "id_env": "GOOGLE_CLIENT_ID",
        "secret_env": "GOOGLE_CLIENT_SECRET",
    },
}


def provider_or_404(provider: str) -> dict:
    config = PROVIDERS.get(provider)

    if not config:
        raise HTTPException(status_code=404, detail="Unknown sign-in provider.")

    return config


def credentials(provider: str):
    """The client id and secret, or None if this provider is not set up."""
    config = provider_or_404(provider)

    client_id = os.getenv(config["id_env"], "").strip()
    client_secret = os.getenv(config["secret_env"], "").strip()

    if not client_id or not client_secret:
        return None

    return client_id, client_secret


def callback_url(provider: str) -> str:
    base = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000").rstrip("/")

    return f"{base}/v1/auth/{provider}/callback"


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")


def sign_state(provider: str) -> str:
    """
    The CSRF guard, as a signed token instead of a database row.

    Without it, an attacker can feed their own authorization code to this
    callback and have the victim's browser sign in as the attacker.
    """
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)

    return jwt.encode(
        {
            "provider": provider,
            "nonce": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + datetime.timedelta(seconds=STATE_TTL_SECONDS),
        },
        jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )


def check_state(state: str, provider: str):
    try:
        payload = jwt.decode(state, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Sign-in took too long. Try again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid sign-in state.")

    if payload.get("provider") != provider:
        raise HTTPException(status_code=400, detail="Sign-in state does not match.")


def back_to_frontend(path: str, **params) -> RedirectResponse:
    query = f"#{urlencode(params)}" if params else ""

    return RedirectResponse(url=f"{frontend_url()}{path}{query}", status_code=302)


# -----------------------------
# IDENTITY PER PROVIDER
# -----------------------------
async def github_identity(client: httpx.AsyncClient, token: str) -> dict:
    profile = await client.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    profile.raise_for_status()
    profile = profile.json()

    email = profile.get("email")
    verified = False

    # A private email is absent from /user, and the primary address is the one
    # we want anyway - not whichever happens to be public.
    emails = await client.get(
        "https://api.github.com/user/emails",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )

    if emails.status_code == 200:
        for entry in emails.json():
            if entry.get("primary"):
                email = entry.get("email") or email
                verified = bool(entry.get("verified"))
                break

    if not email:
        raise HTTPException(
            status_code=400,
            detail="GitHub did not share an email address for this account.",
        )

    return {"email": email, "provider_id": str(profile.get("id", "")), "verified": verified}


async def google_identity(client: httpx.AsyncClient, token: str) -> dict:
    response = await client.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    profile = response.json()

    if not profile.get("email"):
        raise HTTPException(
            status_code=400, detail="Google did not share an email address."
        )

    return {
        "email": profile["email"],
        "provider_id": str(profile.get("sub", "")),
        "verified": bool(profile.get("email_verified")),
    }


IDENTITY = {"github": github_identity, "google": google_identity}


# -----------------------------
# ROUTES
# -----------------------------
@router.get("/providers")
@limiter.limit("60/minute")
async def list_providers(request: Request):
    """
    Which buttons the sign-in page should show.

    A button for a provider with no credentials is a button that fails when
    clicked, so the UI asks first rather than guessing.
    """
    return {
        "providers": [
            {"id": name, "label": config["label"]}
            for name, config in PROVIDERS.items()
            if credentials(name)
        ]
    }


@router.get("/{provider}/login")
@limiter.limit("30/minute")
async def provider_login(request: Request, provider: str):
    """Send the browser to the provider's consent screen."""
    config = provider_or_404(provider)
    pair = credentials(provider)

    if not pair:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{config['label']} sign-in is not configured. Set "
                f"{config['id_env']} and {config['secret_env']} on the server."
            ),
        )

    client_id, _ = pair

    query = urlencode({
        "client_id": client_id,
        "redirect_uri": callback_url(provider),
        "scope": config["scope"],
        "state": sign_state(provider),
        "response_type": "code",
        # Google only; GitHub ignores unknown parameters.
        "access_type": "online",
        "prompt": "select_account",
    })

    return RedirectResponse(url=f"{config['authorize_url']}?{query}", status_code=302)


@router.get("/{provider}/callback")
@limiter.limit("30/minute")
async def provider_callback(
    request: Request,
    provider: str,
    code: str = "",
    state: str = "",
    error: str = "",
):
    """
    Finish the flow and hand the session to the browser.

    The token goes back in the URL fragment, not the query string: a fragment
    is never sent to a server, so it stays out of access logs and out of the
    Referer header on the next navigation. The page reads it and clears it
    immediately.
    """
    config = provider_or_404(provider)

    # The user pressed cancel on the consent screen.
    if error:
        return back_to_frontend("/login", error=f"{config['label']} sign-in cancelled.")

    if not code or not state:
        return back_to_frontend("/login", error="Incomplete sign-in response.")

    check_state(state, provider)

    pair = credentials(provider)

    if not pair:
        return back_to_frontend(
            "/login", error=f"{config['label']} sign-in is not configured."
        )

    client_id, client_secret = pair

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            exchanged = await client.post(
                config["token_url"],
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": callback_url(provider),
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )

            if exchanged.status_code != 200:
                return back_to_frontend(
                    "/login",
                    error=f"{config['label']} rejected the sign-in. Try again.",
                )

            access_token = exchanged.json().get("access_token", "")

            if not access_token:
                return back_to_frontend(
                    "/login", error=f"{config['label']} returned no access token."
                )

            identity = await IDENTITY[provider](client, access_token)

    except httpx.RequestError as problem:
        return back_to_frontend(
            "/login", error=f"Could not reach {config['label']}: {problem}"
        )

    try:
        user = find_or_create_oauth_user(
            email=identity["email"],
            provider=provider,
            provider_id=identity["provider_id"],
            email_verified=identity["verified"],
        )
    except HTTPException as refusal:
        return back_to_frontend("/login", error=refusal.detail)

    session = create_access_token(user)

    return back_to_frontend("/login", token=session["access_token"])
