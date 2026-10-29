"""
Pro plan payments, via Razorpay.

Same trust split as the Stripe module: creating an order changes nothing, and
a plan is granted only on proof from Razorpay. There are two kinds of proof,
both HMACs a customer cannot forge:

  - /verify-payment: the checkout handler's (order_id, payment_id, signature),
    signed with the key secret. This is what upgrades the plan the moment the
    checkout closes, and the only proof available on a machine Razorpay
    cannot reach with a webhook.
  - /webhook/razorpay: Razorpay's own event, signed with the webhook secret.
    The backstop for a browser that closed before the handler ran.

Both are idempotent, so receiving both for one payment is harmless.

Two callers, two credentials: the local app's gateway sends its API key,
and the public pricing page sends the dashboard session token. Either
resolves to the same account, so a plan bought from one shows in both.
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from .accounts import get_current_user
from .auth import DEFAULT_PLAN, UNLIMITED_PLANS, lookup_tenant
from .billing import PRO_PLAN
from .database import users_collection
from .rate_limit import limiter

router = APIRouter(tags=["billing"])

# ₹1600 a month, in paise - Razorpay amounts are in the smallest unit.
PRO_AMOUNT_PAISE = 160000
PRO_CURRENCY = "INR"


def razorpay_keys() -> tuple:
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()

    return key_id, key_secret


def razorpay_client():
    """The configured Razorpay SDK client, or a refusal."""
    key_id, key_secret = razorpay_keys()

    if not key_id or not key_secret:
        raise HTTPException(
            status_code=503,
            detail="Razorpay is not configured on this server.",
        )

    try:
        import razorpay
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="The razorpay package is not installed on this server.",
        )

    return razorpay.Client(auth=(key_id, key_secret))


async def billing_account(
    authorization: str = Header(None),
    x_api_key: str = Header(None, alias="X-API-Key"),
) -> dict:
    """
    The paying account, from a session token or an API key.

    A key is looked up without charging the quota. require_api_key would
    meter the request, and a free account that has used its month would be
    refused the one call that lets it stop being free.
    """
    if authorization:
        return await get_current_user(authorization)

    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Send 'Authorization: Bearer <token>' or an X-API-Key header.",
        )

    tenant = lookup_tenant(x_api_key)

    if not tenant or not tenant.get("user_id"):
        raise HTTPException(status_code=403, detail="Invalid or revoked API key.")

    return tenant


def grant_pro(user_id: str, order_id: str, payment_id: str = "") -> bool:
    """Write the upgrade. Called only after a signature has been verified."""
    if users_collection is None:
        print("⚠️  cannot record a plan change: no account store")
        return False

    changes = {
        "plan": PRO_PLAN,
        "plan_changed_at": datetime.now(timezone.utc),
        "razorpay_order_id": order_id,
    }

    if payment_id:
        changes["razorpay_payment_id"] = payment_id

    result = users_collection.update_one({"user_id": user_id}, {"$set": changes})

    if not result.matched_count:
        print(f"⚠️  plan change for an unknown account: {user_id}")
        return False

    print(f"💳 {user_id} -> {PRO_PLAN} (razorpay {order_id})")

    return True


def order_owner(client, order_id: str) -> str:
    """
    Whose order this is, read back from Razorpay rather than from the caller.

    create_order stamped the user_id into the order's notes, and notes cannot
    be changed from the browser, so this is the account that actually paid.
    """
    order = client.order.fetch(order_id)

    return str((order.get("notes") or {}).get("user_id") or "")


@router.get("/v1/billing/plan")
@limiter.limit("60/minute")
async def plan(request: Request, tenant: dict = Depends(billing_account)):
    """The key owner's current plan, so the UI badge survives a reload."""
    user = (
        users_collection.find_one({"user_id": tenant["user_id"]}, {"plan": 1})
        if users_collection is not None
        else None
    )

    return {"plan": (user or {}).get("plan") or DEFAULT_PLAN}


@router.post("/v1/billing/create-order")
@limiter.limit("20/hour")
async def create_order(request: Request, tenant: dict = Depends(billing_account)):
    """
    Open a Razorpay order for one month of Pro.

    The amount is fixed here, never taken from the request: a client choosing
    its own price would pay ₹1.
    """
    client = razorpay_client()
    user_id = tenant["user_id"]

    # The page hides the button for a paid account, but it may not know yet -
    # the account loads after the page does. Refused here so nobody pays twice.
    account = (
        users_collection.find_one({"user_id": user_id}, {"plan": 1})
        if users_collection is not None
        else None
    )

    if ((account or {}).get("plan") or DEFAULT_PLAN) in UNLIMITED_PLANS:
        raise HTTPException(status_code=409, detail="This account is already on Pro.")

    try:
        order = client.order.create(
            {
                "amount": PRO_AMOUNT_PAISE,
                "currency": PRO_CURRENCY,
                # 40 characters at most; the timestamp keeps retries distinct.
                "receipt": f"pro_{int(datetime.now(timezone.utc).timestamp())}",
                "notes": {"user_id": user_id, "plan": PRO_PLAN},
            }
        )
    except Exception as error:
        # Razorpay's message is for us: it can describe account state.
        print(f"⚠️  razorpay order failed for {user_id}: {error}")

        raise HTTPException(
            status_code=502,
            detail="Could not start checkout. Try again in a moment.",
        )

    print(f"💳 razorpay order {order['id']} for {user_id}")

    return {
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
        # Public by design - checkout.js needs it in the browser. The secret
        # never leaves this server.
        "key_id": razorpay_keys()[0],
    }


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/v1/billing/verify-payment")
@limiter.limit("30/hour")
async def verify_payment(
    request: Request,
    body: VerifyPaymentRequest,
    tenant: dict = Depends(billing_account),
):
    """Grant Pro on the checkout handler's signed proof of payment."""
    client = razorpay_client()

    import razorpay

    try:
        client.utility.verify_payment_signature(body.model_dump())
    except razorpay.errors.SignatureVerificationError:
        print(f"🚫 payment rejected: bad signature on {body.razorpay_order_id}")

        raise HTTPException(status_code=400, detail="Payment could not be verified.")

    # A valid signature proves the payment happened, not that it was this
    # caller's: without this check one paid order could upgrade any account
    # that replays it.
    if order_owner(client, body.razorpay_order_id) != tenant["user_id"]:
        raise HTTPException(status_code=403, detail="This order belongs to another account.")

    grant_pro(tenant["user_id"], body.razorpay_order_id, body.razorpay_payment_id)

    return {"status": "success", "plan": PRO_PLAN}


# Documents the body for /docs without declaring it as a parameter. A declared
# Body would make FastAPI parse and validate the JSON first; the signature is
# over the raw bytes, so the handler has to read those itself.
WEBHOOK_EXAMPLE = {
    "event": "payment.captured",
    "payload": {
        "payment": {
            "entity": {
                "id": "pay_xyz",
                "order_id": "order_xyz",
                "amount": 160000,
                "currency": "INR",
                "status": "captured",
            }
        }
    },
}

WEBHOOK_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["event", "payload"],
                    "properties": {
                        "event": {
                            "type": "string",
                            "enum": ["payment.captured", "order.paid"],
                            "description": "Other events are acknowledged and ignored.",
                        },
                        "payload": {
                            "type": "object",
                            "description": "Razorpay's entities: payment, and order for order.paid.",
                        },
                    },
                },
                "example": WEBHOOK_EXAMPLE,
            }
        },
    },
    "parameters": [
        {
            "name": "X-Razorpay-Signature",
            "in": "header",
            "required": True,
            "description": (
                "HMAC-SHA256 of the exact request body, hex-encoded, keyed with "
                "RAZORPAY_WEBHOOK_SECRET. Any change to the body - even "
                "whitespace - invalidates it."
            ),
            "schema": {"type": "string"},
        }
    ],
}


@router.post("/webhook/razorpay", openapi_extra=WEBHOOK_OPENAPI)
@limiter.exempt
async def webhook(
    request: Request,
    x_razorpay_signature: str = Header(
        None, alias="X-Razorpay-Signature", include_in_schema=False
    ),
):
    """
    Razorpay's event feed.

    Verified on the raw body, before parsing: the signature is over bytes,
    and re-serialised JSON is different bytes. Exempt from the rate limiter
    for the same reason as the Stripe webhook - Razorpay retries, and a
    refused retry leaves a paying customer on the free plan.
    """
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()

    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Razorpay webhook secret is not configured on this server.",
        )

    client = razorpay_client()
    payload = (await request.body()).decode("utf-8")

    import razorpay

    try:
        client.utility.verify_webhook_signature(payload, x_razorpay_signature or "", secret)
    except razorpay.errors.SignatureVerificationError:
        print("🚫 razorpay webhook rejected: bad signature")

        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    event = await request.json()
    kind = event.get("event", "")

    if kind not in ("payment.captured", "order.paid"):
        # Acknowledged and ignored, or Razorpay retries it forever.
        return {"received": True, "handled": False, "type": kind}

    entities = event.get("payload") or {}
    payment = (entities.get("payment") or {}).get("entity") or {}
    order = (entities.get("order") or {}).get("entity") or {}

    order_id = order.get("id") or payment.get("order_id") or ""

    # order.paid carries the order and its notes; payment.captured carries
    # only the payment, so its owner is looked up on the order.
    user_id = str((order.get("notes") or {}).get("user_id") or "")

    if not user_id and order_id:
        try:
            user_id = order_owner(client, order_id)
        except Exception as error:
            print(f"⚠️  could not read razorpay order {order_id}: {error}")

    if not user_id:
        print(f"⚠️  razorpay {kind} with no user_id (order {order_id or 'unknown'})")

        return {"received": True, "handled": False, "reason": "no user_id"}

    grant_pro(user_id, order_id, payment.get("id", ""))

    return {"received": True, "handled": True, "plan": PRO_PLAN}
