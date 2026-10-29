"""
Krish AI - stateless LLM engine.

Documents live on the client. This server only turns a question plus
client-supplied context into a grounded answer, so it stores no PDFs, runs no
vector database, and needs no disk beyond the model itself.

Everything document-related (ChromaDB indexing, uploads, background jobs) moved
to cli.py. The previous server-side implementation is kept in backend/legacy/
for reference; it is not imported and does not run.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import uvicorn

from app.billing import router as billing_router
from app.razorpay_billing import router as razorpay_router
from app.cloud import router as cloud_router
from app.external_integrations import router as external_router
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
    # Replaced by the light-themed /docs below.
    docs_url=None,
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
app.include_router(razorpay_router)
app.include_router(external_router)


# The service map. At /api rather than /, which belongs to the bundled
# frontend in an on-premise install.
@app.get("/api")
async def api_index():
    return {
        "service": "Krish AI stateless engine",
        "stores_documents": False,
        "endpoints": {
            "signup": "POST /v1/auth/signup",
            "login": "POST /v1/auth/login",
            "oauth_providers": "GET /v1/auth/providers",
            "keys": "GET /v1/keys (Bearer)",
            "checkout": "POST /v1/billing/checkout (Bearer)",
            "billing_portal": "POST /v1/billing/portal (Bearer)",
            "stripe_webhook": "POST /v1/billing/webhook (signature)",
            "plan": "GET /v1/billing/plan (Bearer or X-API-Key)",
            "create_order": "POST /v1/billing/create-order (Bearer or X-API-Key)",
            "verify_payment": "POST /v1/billing/verify-payment (Bearer or X-API-Key)",
            "razorpay_webhook": "POST /webhook/razorpay (signature)",
            "leads": "POST /v1/leads (X-API-Key)",
            "leads_webhook": "POST /webhook/leads (X-Webhook-Secret)",
            "generate_key": "POST /v1/keys/generate (Bearer)",
            "revoke_key": "DELETE /v1/keys/{key_id} (Bearer)",
            "ask": "POST /v1/ask-stateless (X-API-Key)",
            "config": "GET /v1/config (X-API-Key)",
            "docs": "/docs",
            "app": "/ (the built frontend, when frontend/dist exists)",
        },
        "client": "python3 cli.py --help",
    }


# A light, minimal skin for Swagger UI: white surfaces, hairline gray
# borders, system sans-serif type. Layered on top of Swagger's own stylesheet
# rather than replacing it, so anything not restyled here keeps working.
DOCS_LIGHT_CSS = """
<style>
  :root { color-scheme: light; }
  body { background: #ffffff; margin: 0; }
  .swagger-ui, .swagger-ui .opblock-tag, .swagger-ui .opblock .opblock-summary-description,
  .swagger-ui .info .title, .swagger-ui .info p, .swagger-ui table, .swagger-ui .btn,
  .swagger-ui input, .swagger-ui textarea, .swagger-ui select, .swagger-ui label,
  .swagger-ui .model, .swagger-ui .model-title, .swagger-ui .parameter__name,
  .swagger-ui .response-col_status, .swagger-ui .tab li, .swagger-ui .markdown p,
  .swagger-ui .renderedMarkdown p {
    font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Inter,
      Roboto, "Helvetica Neue", Arial, sans-serif;
  }
  .swagger-ui code, .swagger-ui pre, .swagger-ui .opblock .opblock-summary-path,
  .swagger-ui .prop-type, .swagger-ui .parameter__type {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  .swagger-ui { color: #171717; }
  .swagger-ui .wrapper { max-width: 1080px; padding: 0 24px; }

  /* Header */
  .swagger-ui .information-container { padding: 8px 0 0; }
  .swagger-ui .info { margin: 40px 0 28px; }
  .swagger-ui .info .title { color: #0a0a0a; font-size: 28px; font-weight: 600; letter-spacing: -0.02em; }
  .swagger-ui .info .title small { background: #f5f5f5; border: 1px solid #e5e5e5; border-radius: 999px; padding: 2px 8px; top: -6px; }
  .swagger-ui .info .title small pre { color: #525252; font-size: 11px; }
  .swagger-ui .info .title small.version-stamp { background: #0a0a0a; border-color: #0a0a0a; }
  .swagger-ui .info .title small.version-stamp pre { color: #ffffff; }
  .swagger-ui .info p, .swagger-ui .info li { color: #525252; font-size: 14px; line-height: 1.6; }
  .swagger-ui .info a, .swagger-ui a.nostyle { color: #0a0a0a; }
  .swagger-ui .scheme-container { background: #ffffff; box-shadow: none; border-top: 1px solid #e5e5e5; border-bottom: 1px solid #e5e5e5; padding: 16px 0; margin: 0 0 24px; }

  /* Tag groups */
  .swagger-ui .opblock-tag { color: #0a0a0a; font-size: 16px; font-weight: 600; border-bottom: 1px solid #e5e5e5; padding: 14px 4px; }
  .swagger-ui .opblock-tag:hover { background: #fafafa; }
  .swagger-ui .opblock-tag small { color: #737373; font-size: 13px; font-weight: 400; }

  /* Operations: white cards, hairline borders, colour only on the method pill */
  .swagger-ui .opblock {
    background: #ffffff !important;
    border: 1px solid #e5e5e5 !important;
    border-radius: 12px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    margin: 0 0 10px;
    overflow: hidden;
  }
  .swagger-ui .opblock:hover { border-color: #d4d4d4 !important; }
  .swagger-ui .opblock.is-open { box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06); }
  .swagger-ui .opblock .opblock-summary { border: 0 !important; padding: 10px 14px; }
  .swagger-ui .opblock .opblock-summary-method {
    border-radius: 6px; font-size: 11px; font-weight: 600; min-width: 64px; padding: 5px 0;
    text-shadow: none; letter-spacing: 0.02em;
  }
  .swagger-ui .opblock .opblock-summary-path { color: #171717; font-size: 14px; font-weight: 500; }
  .swagger-ui .opblock .opblock-summary-description { color: #737373; font-size: 13px; }
  .swagger-ui .opblock .opblock-section-header {
    background: #fafafa; box-shadow: none; border-top: 1px solid #e5e5e5; border-bottom: 1px solid #e5e5e5;
  }
  .swagger-ui .opblock .opblock-section-header h4 { color: #171717; font-size: 13px; font-weight: 600; }
  .swagger-ui .opblock-body, .swagger-ui .responses-inner { background: #ffffff; }
  .swagger-ui .opblock-description-wrapper p, .swagger-ui .opblock-external-docs-wrapper p,
  .swagger-ui .opblock-title_normal p { color: #525252; font-size: 13px; line-height: 1.6; }
  .swagger-ui .opblock.opblock-deprecated { opacity: 0.6; }

  /* Tables */
  .swagger-ui table thead tr th, .swagger-ui table thead tr td {
    color: #737373; font-size: 12px; font-weight: 500; border-bottom: 1px solid #e5e5e5;
  }
  .swagger-ui .parameter__name { color: #171717; font-size: 13px; font-weight: 500; }
  .swagger-ui .parameter__name.required:after { color: #dc2626; }
  .swagger-ui .parameter__name.required span { color: #dc2626; }
  .swagger-ui .parameter__type, .swagger-ui .prop-format { color: #737373; font-size: 12px; }
  .swagger-ui .parameter__in { color: #a3a3a3; font-size: 11px; }
  .swagger-ui .response-col_status { color: #171717; font-weight: 600; }

  /* Inputs: the "chat box" - white, rounded, a soft ring on focus */
  .swagger-ui input[type=text], .swagger-ui input[type=password], .swagger-ui input[type=search],
  .swagger-ui input[type=email], .swagger-ui input[type=file], .swagger-ui textarea, .swagger-ui select {
    background: #ffffff;
    color: #171717;
    border: 1px solid #e5e5e5;
    border-radius: 10px;
    box-shadow: none;
    font-size: 13px;
  }
  .swagger-ui textarea { padding: 12px 14px; min-height: 160px; line-height: 1.55; }
  .swagger-ui textarea.body-param__text { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .swagger-ui input:focus, .swagger-ui textarea:focus, .swagger-ui select:focus {
    border-color: #a3a3a3; outline: none; box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.05);
  }
  .swagger-ui select { padding: 6px 30px 6px 10px; }

  /* Buttons */
  .swagger-ui .btn {
    border: 1px solid #e5e5e5; border-radius: 8px; box-shadow: none; color: #171717;
    background: #ffffff; font-size: 13px; font-weight: 500; padding: 6px 14px;
  }
  .swagger-ui .btn:hover { background: #fafafa; border-color: #d4d4d4; box-shadow: none; }
  .swagger-ui .btn.execute { background: #0a0a0a; border-color: #0a0a0a; color: #ffffff; }
  .swagger-ui .btn.execute:hover { background: #262626; }
  .swagger-ui .btn-group .btn:first-child { border-radius: 8px 0 0 8px; }
  .swagger-ui .btn-group .btn:last-child { border-radius: 0 8px 8px 0; }
  .swagger-ui .btn.authorize { color: #0a0a0a; border-color: #d4d4d4; }
  .swagger-ui .btn.authorize svg { fill: #0a0a0a; }
  .swagger-ui .btn.cancel { color: #dc2626; border-color: #fecaca; }

  /* Code blocks: light, quiet */
  .swagger-ui .highlight-code > .microlight, .swagger-ui .microlight,
  .swagger-ui .opblock-body pre.microlight, .swagger-ui .responses-inner pre {
    background: #fafafa !important; color: #171717 !important;
    border: 1px solid #e5e5e5; border-radius: 10px; padding: 12px 14px !important;
    font-size: 12.5px; line-height: 1.55;
  }
  .swagger-ui .microlight span { color: inherit; }
  .swagger-ui .markdown code, .swagger-ui .renderedMarkdown code {
    background: #f5f5f5; color: #171717; border-radius: 4px; padding: 1px 5px; font-size: 12px;
  }
  .swagger-ui .copy-to-clipboard { background: #ffffff; border: 1px solid #e5e5e5; border-radius: 6px; }
  .swagger-ui .copy-to-clipboard button { filter: invert(1); }

  /* Tabs, models, modals */
  .swagger-ui .tab li { color: #737373; font-size: 12px; }
  .swagger-ui .tab li.active { color: #0a0a0a; font-weight: 600; }
  .swagger-ui .tab li:first-of-type:after { background: #e5e5e5; }
  .swagger-ui section.models { border: 1px solid #e5e5e5; border-radius: 12px; }
  .swagger-ui section.models h4 { color: #0a0a0a; font-size: 16px; font-weight: 600; }
  .swagger-ui section.models.is-open h4 { border-bottom: 1px solid #e5e5e5; }
  .swagger-ui section.models .model-container { background: #ffffff; border-radius: 8px; }
  .swagger-ui section.models .model-container:hover { background: #fafafa; }
  .swagger-ui .model-box { background: transparent; }
  .swagger-ui .model { color: #404040; font-size: 12.5px; }
  .swagger-ui .prop-type { color: #2563eb; }
  .swagger-ui .dialog-ux .backdrop-ux { background: rgba(0, 0, 0, 0.25); }
  .swagger-ui .dialog-ux .modal-ux {
    border: 1px solid #e5e5e5; border-radius: 14px; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.12);
  }
  .swagger-ui .dialog-ux .modal-ux-header { border-bottom: 1px solid #e5e5e5; }
  .swagger-ui .dialog-ux .modal-ux-header h3 { font-size: 16px; font-weight: 600; }
  .swagger-ui .errors-wrapper { background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px; }
  .swagger-ui .loading-container .loading:before { border-color: #e5e5e5; border-top-color: #0a0a0a; }
</style>
"""


@app.get("/docs", include_in_schema=False)
async def docs() -> HTMLResponse:
    page = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - API docs",
    )

    html = page.body.decode("utf-8").replace("</head>", f"{DOCS_LIGHT_CSS}</head>", 1)

    return HTMLResponse(html)


@app.get("/health")
async def health():
    from app.database import db
    from app.generation import MAIN_LLM_MODEL

    return {"status": "ok", "model": MAIN_LLM_MODEL, "key_store": db is not None}


# -----------------------------
# BUNDLED FRONTEND (on-premise)
# -----------------------------
# For an on-premise install the engine also serves the built React app, so
# one port carries everything. In development Vite serves it instead and none
# of this is reached.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# First path segments that belong to the API. An unknown /v1/... must stay a
# JSON 404, not come back as the app's HTML with a 200.
API_PREFIXES = {"api", "v1", "webhook", "docs", "redoc", "openapi.json", "health"}

# Vite puts every hashed bundle under assets/. Mounted only if it exists at
# startup; the catch-all below still serves files from a build made later.
if (FRONTEND_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )


# Registered last, so every API route above wins over it.
@app.get("/{full_path:path}", include_in_schema=False)
async def frontend(full_path: str):
    """
    A file from the build if one matches, otherwise index.html.

    The fallback is what lets React Router own /chat, /dashboard/settings and
    the rest: a hard refresh on any of them still loads the app.
    """
    if full_path.split("/", 1)[0] in API_PREFIXES:
        raise HTTPException(status_code=404, detail="Not Found")

    index = FRONTEND_DIST / "index.html"

    if not index.is_file():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "The frontend has not been built yet.",
                "fix": "Run ./install.sh (or install.bat on Windows), then restart.",
                "api": "/api",
            },
        )

    if full_path:
        candidate = (FRONTEND_DIST / full_path).resolve()

        # resolve() plus the containment check stops ../ walking out of dist.
        if candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST):
            return FileResponse(candidate)

    # index.html must not be cached: it names this build's hashed bundles, and
    # a stale copy after an upgrade would load the previous version.
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
