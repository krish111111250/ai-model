"""
Inbound data from other platforms: CRMs, n8n, form tools.

Two doors for the same data. /v1/leads is for integrations that call an API
with a Krish key; /webhook/leads is for event-driven senders such as n8n,
which are configured once with a shared secret header instead of a key.

Neither is open: a public endpoint that logs whatever it is sent is a free
log-flooding service. For now both only log what arrives; storage comes later.
"""

import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import lookup_tenant
from .rate_limit import limiter

router = APIRouter(tags=["external integrations"])

# Enough to see what a sender is sending without one large payload swamping
# the log.
LOG_PREVIEW_CHARS = 2000

SUCCESS = {"status": "success", "message": "Data received successfully"}


class LeadDataRequest(BaseModel):
    source: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Where the data came from, e.g. 'n8n', 'hubspot', 'website-form'.",
        examples=["n8n"],
    )
    payload: dict[str, Any] = Field(
        ...,
        description="The lead or record itself, in whatever shape the sender uses.",
        examples=[
            {
                "name": "Asha Raman",
                "email": "asha@example.com",
                "phone": "+91 98765 43210",
                "company": "Acme Pvt Ltd",
                "message": "Interested in the Enterprise plan.",
            }
        ],
    )


class LeadDataResponse(BaseModel):
    status: str = Field(examples=["success"])
    message: str = Field(examples=["Data received successfully"])


def log_received(channel: str, sender: str, body: LeadDataRequest):
    preview = json.dumps(body.payload, ensure_ascii=False, default=str)

    if len(preview) > LOG_PREVIEW_CHARS:
        preview = f"{preview[:LOG_PREVIEW_CHARS]}... ({len(preview)} chars)"

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"📥 [{stamp}] {channel} from {sender} (source={body.source}): {preview}")


@router.post("/v1/leads", response_model=LeadDataResponse)
@limiter.limit("120/minute")
async def receive_lead(
    request: Request,
    body: LeadDataRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """
    Receive a lead from an API integration.

    Authenticated with a Krish API key, but not metered: the monthly quota is
    for answers, and a CRM sync should not use it up.
    """
    tenant = lookup_tenant(x_api_key)

    if not tenant:
        raise HTTPException(status_code=403, detail="Invalid or revoked API key.")

    log_received("lead", f"tenant {tenant.get('tenant_id', 'unknown')}", body)

    return SUCCESS


@router.post("/webhook/leads", response_model=LeadDataResponse)
@limiter.limit("120/minute")
async def receive_lead_webhook(
    request: Request,
    body: LeadDataRequest,
    x_webhook_secret: str = Header(
        ...,
        alias="X-Webhook-Secret",
        description="Must equal LEADS_WEBHOOK_SECRET on this server.",
    ),
):
    """
    Receive a lead from a webhook sender such as n8n.

    In n8n: an HTTP Request node, POST to this URL, JSON body with `source`
    and `payload`, and a header `X-Webhook-Secret` set to the server's
    LEADS_WEBHOOK_SECRET.
    """
    secret = os.getenv("LEADS_WEBHOOK_SECRET", "").strip()

    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Leads webhook secret is not configured on this server.",
        )

    # Constant-time, so the secret cannot be guessed a character at a time
    # from response timings.
    if not hmac.compare_digest(x_webhook_secret.encode(), secret.encode()):
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")

    log_received("webhook", "webhook sender", body)

    return SUCCESS
