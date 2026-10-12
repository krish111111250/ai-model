"""
Stateless LLM engine API.

The client keeps the documents. It chunks, embeds and searches on its own
machine, then sends only the few chunks it already selected. The server holds
nothing: no PDFs, no vector store, no chunk text after the response is sent.
That is what makes this usable for customers who cannot let documents leave
their machines, and it is why the server's disk and RAM stopped being the
bottleneck.

The one piece of server state is the API key table, which is needed to
authenticate and rate-limit callers.
"""

from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .accounts import get_current_user
from .auth import (
    generate_api_key,
    list_keys_for_user,
    require_api_key,
    revoke_key,
)
from .generation import (
    GROUNDING_MIN_RATIO,
    MAIN_LLM_MODEL,
    answer_from_context,
    expand_query,
)
from .rate_limit import limiter

router = APIRouter(prefix="/v1", tags=["stateless"])

# A guard, not a tuning knob: beyond this the local model's context window
# overflows and answers degrade. Clients should send their top 3-5 chunks.
MAX_CHUNKS = 12
MAX_CONTEXT_CHARS = 24000


class ContextChunk(BaseModel):
    text: str
    page: Optional[int] = None
    source: Optional[str] = None
    score: Optional[float] = None


class AskStatelessRequest(BaseModel):
    query: str = Field(..., description="The user's question")
    context: List[Union[str, ContextChunk]] = Field(
        default_factory=list,
        description="Relevant chunks retrieved on the client, best first",
    )
    min_ratio: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Grounding strictness: 0.65 strict, 0.4 balanced, 0.25 loose",
    )


class AskStatelessResponse(BaseModel):
    answer: str
    grounded: bool
    chunks_used: int
    model: str


@router.post("/ask-stateless", response_model=AskStatelessResponse)
@limiter.limit("30/minute")
async def ask_stateless(
    request: Request,
    body: AskStatelessRequest,
    tenant: dict = Depends(require_api_key),
):
    """
    Answer a question from context supplied by the caller.

    Nothing is stored. The chunks exist only for the life of this request.
    """
    if not (body.query or "").strip():
        raise HTTPException(status_code=400, detail="query is required.")

    if not body.context:
        raise HTTPException(
            status_code=400,
            detail="context is required: send the chunks your client retrieved.",
        )

    chunks = []
    total_chars = 0

    for item in body.context[:MAX_CHUNKS]:
        chunk = {"text": item} if isinstance(item, str) else item.model_dump()
        text = (chunk.get("text") or "").strip()

        if not text:
            continue

        # Trim rather than reject: a client that sends too much still gets an
        # answer from the part that fits.
        if total_chars + len(text) > MAX_CONTEXT_CHARS:
            text = text[: max(0, MAX_CONTEXT_CHARS - total_chars)]

        if not text:
            break

        total_chars += len(text)
        chunks.append({"text": text, "page": chunk.get("page")})

    if not chunks:
        raise HTTPException(status_code=400, detail="context contained no usable text.")

    result = answer_from_context(body.query, chunks, min_ratio=body.min_ratio)

    print(
        f"🧠 [{tenant['tenant_id']}] stateless ask: {len(chunks)} chunks, "
        f"{total_chars} chars, grounded={result['grounded']}"
    )

    return AskStatelessResponse(
        answer=result["answer"],
        grounded=result["grounded"],
        chunks_used=len(chunks),
        model=MAIN_LLM_MODEL,
    )


class ExpandRequest(BaseModel):
    query: str = Field(..., description="The user's question, as typed")


@router.post("/expand")
@limiter.limit("60/minute")
async def expand(
    request: Request,
    body: ExpandRequest,
    tenant: dict = Depends(require_api_key),
):
    """
    Words a document answering this question might use.

    The client has no language model - that is the point of the architecture -
    so expansion has to happen here. Only the question is sent; no document
    text is involved, and nothing is stored.
    """
    question = (body.query or "").strip()

    if not question:
        raise HTTPException(status_code=400, detail="query is required.")

    terms = expand_query(question)

    print(f"🔎 [{tenant['tenant_id']}] expanded: {len(terms)} term(s)")

    return {"query": question, "terms": terms, "model": MAIN_LLM_MODEL}


class KeyRequest(BaseModel):
    name: str = ""


@router.post("/keys/generate")
@limiter.limit("20/hour")
async def create_key(
    request: Request,
    body: KeyRequest,
    user: dict = Depends(get_current_user),
):
    """
    Issue an API key for the signed-in account.

    This used to be open, which made it a free-key faucet for anyone who found
    the URL - the per-IP rate limit was the only thing standing in the way.
    Keys now belong to an account, which is also what makes listing and
    revoking them possible.
    """
    created = generate_api_key(name=body.name, user_id=user["user_id"])

    return {
        **created,
        "note": "Store this key now. It is hashed in the database and cannot be shown again.",
        "usage": "Send it as the X-API-Key header on /v1 requests.",
    }


@router.get("/keys")
@limiter.limit("120/minute")
async def list_keys(request: Request, user: dict = Depends(get_current_user)):
    """
    Every key on this account.

    No plaintext here, and not because it is withheld: only a hash was ever
    stored, so the token genuinely cannot be reproduced. Each entry carries a
    masked tail to tell keys apart.
    """
    keys = list_keys_for_user(user["user_id"])

    return {
        "keys": keys,
        "active": sum(1 for key in keys if not key["revoked_at"]),
        "total": len(keys),
    }


@router.delete("/keys/{key_id}")
@limiter.limit("60/minute")
async def delete_key(
    request: Request,
    key_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Revoke a key. Soft: the row stays, with the time it was killed.

    The next request using it fails at require_api_key, so revocation is
    immediate - there is no cache to wait out.
    """
    return {
        "revoked": revoke_key(user["user_id"], key_id),
        "message": "Key revoked. Requests using it now fail with 403.",
    }


@router.get("/keys/me")
@limiter.limit("60/minute")
async def key_info(request: Request, tenant: dict = Depends(require_api_key)):
    return {
        "tenant_id": tenant["tenant_id"],
        "name": tenant.get("name", ""),
        "created_at": str(tenant.get("created_at", "")),
        "request_count": tenant.get("request_count", 0),
    }


@router.get("/config")
@limiter.limit("60/minute")
async def engine_config(request: Request, tenant: dict = Depends(require_api_key)):
    """What the engine is running, so a client can check compatibility."""
    return {
        "model": MAIN_LLM_MODEL,
        "default_min_ratio": GROUNDING_MIN_RATIO,
        "max_chunks": MAX_CHUNKS,
        "max_context_chars": MAX_CONTEXT_CHARS,
        "stores_documents": False,
    }
