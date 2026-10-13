"""
Krish AI - stateless LLM engine.

Documents live on the client. This server only turns a question plus
client-supplied context into a grounded answer, so it stores no PDFs, runs no
vector database, and needs no disk beyond the model itself.

Everything document-related (ChromaDB indexing, uploads, background jobs) moved
to cli.py. The previous server-side implementation is kept in backend/legacy/
for reference; it is not imported and does not run.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import uvicorn

from app.billing import router as billing_router
from app.cloud import router as cloud_router
from app.oauth import router as oauth_router
from app.rate_limit import limiter
from app.stateless import router as stateless_router

app = FastAPI(
    title="Krish AI Engine",
    description=(
        "Stateless RAG answer engine. Your documents never leave your machine: "
        "the client retrieves locally and sends only the selected context."
    ),
    version="3.0.0",
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                f"Rate limit exceeded: {exc.detail}. One model answers one "
                "question at a time - slow down and retry."
            )
        },
    )


# Open CORS: clients are CLIs and other people's apps, not one known origin.
# allow_credentials stays False - browsers reject a wildcard origin with
# credentials, and this API authenticates by header, not cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stateless_router)
app.include_router(cloud_router)
app.include_router(oauth_router)
app.include_router(billing_router)


@app.get("/")
async def root():
    return {
        "service": "Krish AI stateless engine",
        "stores_documents": False,
        "endpoints": {
            "signup": "POST /v1/auth/signup",
            "login": "POST /v1/auth/login",
            "oauth_providers": "GET /v1/auth/providers",
            "keys": "GET /v1/keys (Bearer)",
            "checkout": "POST /v1/billing/checkout (Bearer)",
            "stripe_webhook": "POST /v1/billing/webhook (signature)",
            "generate_key": "POST /v1/keys/generate (Bearer)",
            "revoke_key": "DELETE /v1/keys/{key_id} (Bearer)",
            "ask": "POST /v1/ask-stateless (X-API-Key)",
            "config": "GET /v1/config (X-API-Key)",
            "docs": "/docs",
        },
        "client": "python3 cli.py --help",
    }


@app.get("/health")
async def health():
    from app.database import db
    from app.generation import MAIN_LLM_MODEL

    return {"status": "ok", "model": MAIN_LLM_MODEL, "key_store": db is not None}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
