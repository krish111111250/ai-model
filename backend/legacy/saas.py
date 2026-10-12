"""
Multi-tenant SaaS API.

Routes here are for programmatic callers holding an API key. The existing
routes in routers.py stay as they are for the bundled React app, which runs
without a key on the local tenant.

Isolation rule: tenant_id comes from the API key and nothing else. It is never
read from the request body, so a caller cannot ask for another tenant's data.
"""

import os
import shutil
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .auth import generate_api_key, require_api_key
from .database import api_keys_collection, document_collection, jobs_collection
from .rag import delete_document_by_id, process_and_store_document, query_rag
from .rate_limit import limiter

router = APIRouter(prefix="/v1", tags=["saas"])

# Each tenant's uploads run under one user id; documents are separated by
# tenant, not by user, in this API.
API_USER_ID = "api_user"


class KeyRequest(BaseModel):
    name: str = ""
    webhook_url: str = ""


class AskRequest(BaseModel):
    query: str
    document_id: Optional[str] = None
    document_ids: List[str] = []
    document_mode: str = "single"
    session_id: str = "api_session"


class AskResponse(BaseModel):
    answer: str
    sources: List[dict] = []
    source_labels: List[str] = []
    document_mode: str
    grounded: bool


def send_webhook(url: str, payload: dict):
    """Notify the caller that their document finished processing."""
    if not url:
        return

    try:
        import httpx

        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload)

        print(f"🔔 Webhook {url} -> {response.status_code}")
    except Exception as e:
        # A caller's broken webhook must never fail their upload.
        print(f"⚠️ Webhook to {url} failed: {e}")


def record_job(job_id: str, tenant_id: str, **fields):
    if jobs_collection is None:
        return

    try:
        jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": {"job_id": job_id, "tenant_id": tenant_id, **fields}},
            upsert=True,
        )
    except Exception as e:
        print(f"⚠️ Could not record job {job_id}: {e}")


def process_upload_job(
    job_id: str,
    temp_path: str,
    tenant_id: str,
    webhook_url: str,
):
    """Runs in the background: index the PDF, then fire the webhook."""
    result = {}

    try:
        result = process_and_store_document(
            temp_path,
            user_id=API_USER_ID,
            tenant_id=tenant_id,
        )
        status = result.get("status", "success")
    except Exception as e:
        status = "error"
        result = {"status": "error", "message": str(e)}
        print(f"❌ Upload job {job_id} failed: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    record_job(
        job_id,
        tenant_id,
        status=status,
        document_id=result.get("document_id"),
        chunks=result.get("chunks", 0),
        message=result.get("message", ""),
        finished_at=datetime.utcnow(),
    )

    send_webhook(webhook_url, {
        "event": "document.processed",
        "job_id": job_id,
        "status": status,
        "document_id": result.get("document_id"),
        "chunks": result.get("chunks", 0),
        "message": result.get("message", ""),
        "finished_at": datetime.utcnow().isoformat(),
    })


@router.post("/keys/generate")
@limiter.limit("5/hour")
async def create_key(request: Request, body: KeyRequest):
    """
    Issue an API key.

    The plaintext key is returned once and stored only as a hash, so it cannot
    be recovered later - the caller must save it now.
    """
    created = generate_api_key(name=body.name, webhook_url=body.webhook_url)

    return {
        **created,
        "note": "Store this key now. It is hashed in the database and cannot be shown again.",
        "usage": "Send it as the X-API-Key header on /v1 requests.",
    }


@router.get("/keys/me")
@limiter.limit("60/minute")
async def key_info(request: Request, tenant: dict = Depends(require_api_key)):
    return {
        "tenant_id": tenant["tenant_id"],
        "name": tenant.get("name", ""),
        "webhook_url": tenant.get("webhook_url", ""),
        "created_at": str(tenant.get("created_at", "")),
        "request_count": tenant.get("request_count", 0),
    }


@router.post("/upload")
@limiter.limit("10/minute")
async def upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    webhook_url: str = Form(""),
    wait: bool = Form(False),
    tenant: dict = Depends(require_api_key),
):
    """
    Upload a PDF for this tenant.

    By default the PDF is indexed in the background and a webhook fires when it
    finishes, because a large PDF takes longer than a sensible HTTP timeout.
    Pass wait=true to block until indexing completes instead.
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    tenant_id = tenant["tenant_id"]
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    temp_path = f"temp_{job_id}_{os.path.basename(file.filename)}"

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")

    target_webhook = webhook_url or tenant.get("webhook_url", "")

    record_job(
        job_id,
        tenant_id,
        status="processing",
        file_name=file.filename,
        webhook_url=target_webhook,
        created_at=datetime.utcnow(),
    )

    if wait:
        process_upload_job(job_id, temp_path, tenant_id, target_webhook)
        job = jobs_collection.find_one({"job_id": job_id}, {"_id": 0}) if jobs_collection is not None else {}

        if job and job.get("status") not in ("success", "processing"):
            raise HTTPException(status_code=422, detail=job.get("message", "Processing failed."))

        return {"job_id": job_id, **{k: v for k, v in (job or {}).items() if k != "tenant_id"}}

    background_tasks.add_task(process_upload_job, job_id, temp_path, tenant_id, target_webhook)

    return {
        "job_id": job_id,
        "status": "processing",
        "file_name": file.filename,
        "webhook_url": target_webhook,
        "poll": f"/v1/jobs/{job_id}",
    }


@router.get("/jobs/{job_id}")
@limiter.limit("120/minute")
async def job_status(request: Request, job_id: str, tenant: dict = Depends(require_api_key)):
    if jobs_collection is None:
        raise HTTPException(status_code=500, detail="MongoDB is not connected.")

    job = jobs_collection.find_one(
        {"job_id": job_id, "tenant_id": tenant["tenant_id"]},
        {"_id": 0, "tenant_id": 0},
    )

    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    return job


@router.get("/documents")
@limiter.limit("60/minute")
async def list_documents(request: Request, tenant: dict = Depends(require_api_key)):
    if document_collection is None:
        return {"documents": []}

    records = document_collection.find(
        {"tenant_id": tenant["tenant_id"]}
    ).sort("uploaded_at", -1)

    return {
        "documents": [
            {
                "document_id": record.get("document_id"),
                "file_name": record.get("file_name"),
                "pages": record.get("pages", 0),
                "total_chunks": record.get("total_chunks", 0),
                "uploaded_at": str(record.get("uploaded_at", "")),
            }
            for record in records
        ]
    }


@router.post("/ask", response_model=AskResponse)
@limiter.limit("30/minute")
async def ask(request: Request, body: AskRequest, tenant: dict = Depends(require_api_key)):
    """Answer a question from this tenant's documents only."""
    if not (body.query or "").strip():
        raise HTTPException(status_code=400, detail="query is required.")

    mode = (body.document_mode or "single").lower()
    document_ids = [doc_id for doc_id in (body.document_ids or []) if doc_id]

    if mode == "single" and not body.document_id:
        # Convenience: with one document uploaded, there is nothing to choose.
        if document_collection is not None:
            owned = list(
                document_collection.find({"tenant_id": tenant["tenant_id"]})
                .sort("uploaded_at", -1)
                .limit(2)
            )

            if len(owned) == 1:
                body.document_id = owned[0].get("document_id")

        if not body.document_id:
            raise HTTPException(
                status_code=400,
                detail="document_id is required when the tenant has several documents.",
            )

    if mode == "multiple" and not document_ids:
        raise HTTPException(status_code=400, detail="document_ids is required for multiple mode.")

    result = query_rag(
        user_query=body.query,
        language="english",
        session_id=body.session_id,
        user_id=API_USER_ID,
        document_id=body.document_id,
        document_mode=mode,
        document_ids=document_ids,
        tenant_id=tenant["tenant_id"],
    )

    answer = result.get("answer", "")
    sources = result.get("sources", [])

    return AskResponse(
        answer=answer,
        sources=sources,
        source_labels=result.get("source_labels", []),
        document_mode=mode,
        # False when the system found nothing to stand on and said so.
        grounded=bool(sources),
    )


@router.delete("/documents/{document_id}")
@limiter.limit("30/minute")
async def delete_document(request: Request, document_id: str, tenant: dict = Depends(require_api_key)):
    result = delete_document_by_id(
        document_id=document_id,
        user_id=API_USER_ID,
        tenant_id=tenant["tenant_id"],
    )

    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Document not found.")

    return result


@router.delete("/keys/revoke")
@limiter.limit("10/hour")
async def revoke_key(request: Request, tenant: dict = Depends(require_api_key)):
    if api_keys_collection is None:
        raise HTTPException(status_code=500, detail="MongoDB is not connected.")

    api_keys_collection.update_one(
        {"key_hash": tenant["key_hash"]},
        {"$set": {"revoked": True, "revoked_at": datetime.utcnow()}},
    )

    return {"status": "success", "message": "API key revoked.", "tenant_id": tenant["tenant_id"]}
