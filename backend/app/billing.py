"""
Subscriptions, via Stripe.

Two endpoints with opposite trust models. /checkout is called by a signed-in
browser and does nothing but start a session - it never changes a plan.
/webhook is called by Stripe, carries no session, and is the only thing in the
system that grants a paid plan. That asymmetry is the design: if a customer
could tell us they had paid, they would.
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from .accounts import get_current_user
from .auth import DEFAULT_PLAN
from .database import users_collection
from .rate_limit import limiter

router = APIRouter(prefix="/v1/billing", tags=["billing"])

PRO_PLAN = "pro"


def stripe_client():
    """The configured Stripe SDK, or a refusal."""
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()

    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured on this server.",
        )

    try:
        import stripe
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="The stripe package is not installed on this server.",
        )

    stripe.api_key = secret

    return stripe


def price_id() -> str:
    return os.getenv("STRIPE_PRICE_PRO", "price_dummy123").strip()


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")


def billing_configured() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY", "").strip())


def plain(value) -> dict:
    """
    A plain dict out of a Stripe object, a dict, or nothing.

    The SDK hands back StripeObjects, which look dict-like and are not: .get()
    raises, dict() raises, and to_dict() only converts one level.
    """
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    to_dict = getattr(value, "to_dict", None)

    return to_dict() if callable(to_dict) else {}


def set_plan(user_id: str, plan: str, customer_id: str = "", subscription_id: str = ""):
    """
    Write a plan change. Called only from the webhook.

    stripe_customer_id is what later events are matched on:
    customer.subscription.deleted carries a customer, not our user_id, so
    without this there would be no way to know whose plan to revert.
    """
    if users_collection is None:
        print("⚠️  cannot record a plan change: no account store")
        return False

    changes = {"plan": plan, "plan_changed_at": datetime.now(timezone.utc)}

    if customer_id:
        changes["stripe_customer_id"] = customer_id

    if subscription_id:
        changes["stripe_subscription_id"] = subscription_id

    result = users_collection.update_one({"user_id": user_id}, {"$set": changes})

    if not result.matched_count:
        print(f"⚠️  plan change for an unknown account: {user_id}")
        return False

    print(f"💳 {user_id} -> {plan}")

    return True


@router.get("/config")
@limiter.limit("60/minute")
async def config(request: Request):
    """
    Whether billing works here, so the UI can hide a button that cannot.

    No authentication: it reveals only whether this deployment has Stripe keys.
    """
    return {
        "enabled": billing_configured(),
        "plan": PRO_PLAN,
        "price": "$20",
        "interval": "month",
    }


@router.post("/checkout")
@limiter.limit("20/hour")
async def checkout(request: Request, user: dict = Depends(get_current_user)):
    """
    Start a Stripe Checkout session for the signed-in account.

    The account is taken from the session, never from the request body: a body
    naming a user_id would let anyone buy a plan for - or more usefully, as
    someone else.
    """
    stripe = stripe_client()
    user_id = user["user_id"]

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id(), "quantity": 1}],
            # Both, on purpose. client_reference_id is what checkout.session
            # events carry back; metadata survives onto the subscription, so a
            # later event can still be traced to an account.
            client_reference_id=user_id,
            metadata={"user_id": user_id},
            subscription_data={"metadata": {"user_id": user_id}},
            # Reuse the customer we already know, so a second subscription does
            # not create a second customer for the same person.
            customer=user.get("stripe_customer_id") or None,
            customer_email=None if user.get("stripe_customer_id") else user.get("email"),
            success_url=f"{frontend_url()}/dashboard?checkout=success",
            cancel_url=f"{frontend_url()}/dashboard?checkout=cancelled",
        )
    except Exception as error:
        # Stripe's message is for us, not the customer: it can name price ids
        # and account state.
        print(f"⚠️  checkout session failed for {user_id}: {error}")

        raise HTTPException(
            status_code=502,
            detail="Could not start checkout. Try again in a moment.",
        )

    print(f"💳 checkout started for {user_id}")

    return {"url": session.url, "session_id": session.id}


@router.post("/portal")
@limiter.limit("30/hour")
async def portal(request: Request, user: dict = Depends(get_current_user)):
    """
    A link into Stripe's hosted customer portal.

    Invoices, card changes and cancellation all live there, which is why this
    endpoint is three lines and there is no billing UI to maintain. Stripe
    tells us what happened afterwards through the webhook; this returns the
    customer to the dashboard but promises nothing about what they did.
    """
    stripe = stripe_client()
    customer_id = (user.get("stripe_customer_id") or "").strip()

    if not customer_id:
        # No customer means they never checked out - a plan set by hand, or an
        # admin exemption. There is nothing for the portal to show, and asking
        # Stripe would just return an error about an unknown customer.
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer on this account. Subscribe first.",
        )

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{frontend_url()}/dashboard?portal=return",
        )
    except Exception as error:
        print(f"⚠️  portal session failed for {user['user_id']}: {error}")

        raise HTTPException(
            status_code=502,
            detail="Could not open the billing portal. Try again in a moment.",
        )

    print(f"💳 portal opened for {user['user_id']}")

    return {"url": session.url}


@router.post("/webhook")
@limiter.exempt
async def webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Stripe's side of the conversation.

    Unauthenticated by necessity - Stripe has no session - and therefore
    verified by signature on the raw body. The body must not be parsed before
    verification: re-serialising JSON changes bytes, and the signature is over
    bytes.

    Exempt from the rate limiter. The default 240/minute is keyed by IP, and
    Stripe retries from a pool of its own addresses; a burst of legitimate
    retries being refused would silently leave a paying customer on the free
    plan.
    """
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Webhook secret is not configured on this server.",
        )

    stripe = stripe_client()
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed webhook payload.")
    except stripe.error.SignatureVerificationError:
        # The one line that stands between this endpoint and anyone on the
        # internet granting themselves a paid plan.
        print("🚫 webhook rejected: bad signature")

        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    kind = event["type"]

    # A StripeObject, not a dict: .get() on it raises, and so does dict() -
    # it is neither iterable nor a mapping. to_dict() is shallow, so nested
    # values go through plain() as well.
    data = plain(event["data"]["object"])

    if kind == "checkout.session.completed":
        user_id = (
            data.get("client_reference_id")
            or plain(data.get("metadata")).get("user_id")
            or ""
        )

        if not user_id:
            # Nothing to act on, but a 200 so Stripe stops retrying an event
            # that will never succeed.
            print("⚠️  checkout.session.completed with no user_id")

            return {"received": True, "handled": False, "reason": "no user_id"}

        set_plan(
            user_id,
            PRO_PLAN,
            customer_id=str(data.get("customer") or ""),
            subscription_id=str(data.get("subscription") or ""),
        )

        return {"received": True, "handled": True, "plan": PRO_PLAN}

    if kind == "customer.subscription.deleted":
        # This event names a customer and a subscription, not our user, which
        # is why checkout saved the customer id.
        user_id = plain(data.get("metadata")).get("user_id") or ""

        if not user_id and users_collection is not None:
            owner = users_collection.find_one(
                {"stripe_customer_id": str(data.get("customer") or "")},
                {"user_id": 1},
            )
            user_id = (owner or {}).get("user_id", "")

        if not user_id:
            print(f"⚠️  subscription deleted for an unmatched customer: {data.get('customer')}")

            return {"received": True, "handled": False, "reason": "unknown customer"}

        set_plan(user_id, DEFAULT_PLAN)

        return {"received": True, "handled": True, "plan": DEFAULT_PLAN}

    # Everything else is acknowledged and ignored. Returning an error would
    # make Stripe retry an event this app has no opinion about.
    return {"received": True, "handled": False, "type": kind}
