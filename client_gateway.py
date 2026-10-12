#!/usr/bin/env python3
"""
Krish AI - local client gateway.

This runs on the customer's own machine and is what the React app talks to.
It does everything that touches the document: reads the PDF, splits it,
embeds it, stores it in ~/.krish, and searches it. The only thing that ever
leaves this machine is the question plus the handful of chunks that matched
it, sent to the answer engine, which stores nothing.

    pip install fastapi uvicorn chromadb pymupdf httpx python-multipart
    export KRISH_API_KEY=krish_...          # from your account dashboard
    python3 client_gateway.py                # serves http://localhost:8001

Then point the React app at http://localhost:8001 instead of the engine.

Search is hybrid: keywords (pure-Python TF-IDF) and meaning (all-MiniLM-L6-v2
on onnxruntime), fused into one top 4. The model is fetched once (~80MB) on
first start, in the background, so uploads and questions never wait for it -
until it is ready, answers come from the keyword half alone.
Set KRISH_RETRIEVAL=lexical to skip the download entirely.

Where things live:
    ~/.krish/chroma/     the local vector store
    ~/.krish/krish.db    documents, conversations and messages (SQLite)
    ~/.krish/lexicon.json  word statistics used to weight searches
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# cli.py holds the document logic. Importing it keeps one implementation of
# chunking, embedding and retrieval instead of two that drift apart.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli

HOME = Path(os.environ.get("KRISH_HOME", Path.home() / ".krish")).expanduser()
DB_PATH = HOME / "krish.db"
TMP_DIR = HOME / "tmp"
AUDIO_DIR = HOME / "audio"

ENGINE_URL = os.environ.get("KRISH_API_URL", "http://localhost:8000").rstrip("/")
PORT = int(os.environ.get("KRISH_GATEWAY_PORT", "8001"))
TOP_K = int(os.environ.get("KRISH_TOP_K", str(cli.TOP_K)))

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
NOT_AVAILABLE = "This information is not available in the uploaded document."

# Below this semantic similarity, the best-matching chunk is not about the
# question at all and the engine is not worth calling.
#
# Calibrated over 57 measurements on three documents (5, 40 and 77 chunks).
# It is set low on purpose: the lowest-scoring *valid* question measured was
# 0.1219, so 0.10 leaves 0.02 of headroom and refused none of the 27 valid
# questions, while catching 11 of 30 deliberately off-topic ones.
#
# It cannot be raised to catch the rest. Valid and off-topic scores overlap -
# "what is the price of gold today" scored 0.189 against a pricing document
# while "is there a charge for usage" scored 0.122 on the same one - so a
# higher floor starts refusing real questions. The guard against a plausible
# answer to an out-of-scope question lives in the engine's grounding checks,
# not here.
RELEVANCE_FLOOR = float(os.environ.get("KRISH_RELEVANCE_FLOOR", "0.10"))

# Query expansion: ask the engine's model what words a document answering this
# question would use, and search for those too.
#
#   augment  expansion searches beside the question   (default)
#   replace  expansion searches instead of it
#   off      no expansion call at all
#
# Measured on a 40-page manual, 18 questions whose answers are worded unlike
# the question: the question alone found 18 of 18 in the top 4 at 25ms.
# "replace" found 15 of 18 at ~1.2s, because a 3B model expands "appraisals"
# into property valuation and "hotel limit" into room occupancy. "augment"
# keeps the question's own hits, so it cannot score below the baseline, and
# pays the same ~1.2s. The default is augment because it was asked for; set
# this to off to get the 25ms path back.
QUERY_EXPANSION = (os.environ.get("KRISH_QUERY_EXPANSION") or "augment").strip().lower()

# Expansion is an optimisation, not a dependency. Past this, retrieval runs on
# the question alone rather than making the user wait.
EXPANSION_TIMEOUT = float(os.environ.get("KRISH_EXPANSION_TIMEOUT", "3.0"))

# Only questions whose first pass comes back weaker than this pay for
# expansion. Retrieval scoring 0.30 or better already had the answer in the
# top 4 in every case measured, so the second pass would cost 1.5s to
# re-confirm what the first pass found. Below it is where expansion moved
# top-1 from 11 of 18 to 15 of 18.
EXPANSION_TRIGGER = float(os.environ.get("KRISH_EXPANSION_TRIGGER", "0.30"))

# Questions repeat, and an expansion never changes for the same question.
_expansion_cache = {}
EXPANSION_CACHE_MAX = 500


# -----------------------------
# CONFIG
# -----------------------------
def load_config() -> dict:
    """Settings from the environment, falling back to ~/.krish/config.json."""
    config = {}
    config_file = HOME / "config.json"

    if config_file.exists():
        try:
            config = json.loads(config_file.read_text()) or {}
        except Exception as error:
            print(f"⚠️  Ignoring unreadable {config_file}: {error}")

    api_key = os.environ.get("KRISH_API_KEY") or config.get("api_key") or ""
    engine_url = os.environ.get("KRISH_API_URL") or config.get("engine_url") or ENGINE_URL

    return {"api_key": api_key.strip(), "engine_url": engine_url.rstrip("/")}


CONFIG = load_config()


def require_engine_key() -> str:
    if not CONFIG["api_key"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "No engine API key configured. Set KRISH_API_KEY (or api_key in "
                "~/.krish/config.json) and restart the gateway."
            ),
        )

    return CONFIG["api_key"]


# -----------------------------
# LOCAL DATABASE
# -----------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id   TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    pages         INTEGER DEFAULT 0,
    total_chunks  INTEGER DEFAULT 0,
    sha256        TEXT,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    title         TEXT,
    document_mode TEXT DEFAULT 'single',
    document_id   TEXT,
    document_ids  TEXT DEFAULT '[]',
    created_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    sources       TEXT DEFAULT '[]',
    source_labels TEXT DEFAULT '[]',
    created_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id);
CREATE INDEX IF NOT EXISTS idx_documents_user ON documents (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);
"""


def connect() -> sqlite3.Connection:
    """A fresh connection per request: SQLite objects are not thread-safe."""
    HOME.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row

    return connection


def init_db():
    with connect() as connection:
        connection.executescript(SCHEMA)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -----------------------------
# LOCAL VECTOR STORE
# -----------------------------
_collection = None


def collection():
    """The local Chroma collection, opened once and reused."""
    global _collection

    if _collection is None:
        _collection = cli.get_collection(HOME)

    return _collection


def where_clause(conditions: List[dict]):
    """Chroma wants an explicit $and once there is more than one condition."""
    conditions = [condition for condition in conditions if condition]

    if not conditions:
        return None

    if len(conditions) == 1:
        return conditions[0]

    return {"$and": conditions}


def document_filter(user_id: str, mode: str, document_id, document_ids):
    """Translate the UI's document selection into a metadata filter."""
    scope = [{"user_id": user_id}]

    if mode == "single":
        if not document_id:
            raise HTTPException(status_code=400, detail="No document selected.")

        scope.append({"document_id": document_id})

    elif mode == "multiple":
        ids = [value for value in (document_ids or []) if value]

        if not ids:
            raise HTTPException(status_code=400, detail="No documents selected.")

        scope.append({"document_id": {"$in": ids}})

    return where_clause(scope)


# -----------------------------
# APP
# -----------------------------
def reconcile_store():
    """
    Drop chunks that no listed document owns.

    They can only come from an upload that died midway. Left alone they are
    unreachable - not listed, so not deletable - while still being searchable,
    which is exactly the kind of leftover a privacy-first tool must not keep.
    """
    try:
        with connect() as connection:
            known = {
                row["document_id"]
                for row in connection.execute("SELECT document_id FROM documents")
            }

        records = collection().get(include=["metadatas"])
        ids = records.get("ids") or []
        metadatas = records.get("metadatas") or []

        orphans = [
            chunk_id
            for index, chunk_id in enumerate(ids)
            if (metadatas[index] or {}).get("document_id") not in known
        ]

        if orphans:
            cli.delete_chunks(HOME, orphans)
            print(f"🧹 removed {len(orphans)} orphaned chunk(s) from an interrupted upload")

    except Exception as error:
        print(f"⚠️  store reconciliation failed: {error}")


def prepare_semantic():
    """
    Load the embedding model, then catch up anything indexed without it.

    This runs on a background thread at startup: the first start downloads
    ~80MB, and nothing the user does should wait for it. Questions asked in
    the meantime are answered by the keyword retriever.
    """
    cli.warm_semantic()

    if cli.semantic_ready():
        try:
            added = cli.backfill_semantic(HOME)

            if added:
                print(f"🧠 semantic index caught up: {added} chunk(s)")
        except Exception as error:
            print(f"⚠️  semantic backfill failed: {error}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()

    HOME.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    indexed = collection().count()

    print("\n🔒 Krish AI local gateway")
    print(f"   store:      {HOME}")
    print(f"   indexed:    {indexed} chunks")
    print(f"   retrieval:  {cli.RETRIEVAL}")
    print(f"   engine:     {CONFIG['engine_url']}")
    print(f"   api key:    {'set' if CONFIG['api_key'] else 'MISSING - set KRISH_API_KEY'}")
    print(f"   listening:  http://localhost:{PORT}\n")

    reconcile_store()

    if cli.semantic_enabled():
        threading.Thread(target=prepare_semantic, daemon=True).start()

    yield


app = FastAPI(
    lifespan=lifespan,
    title="Krish AI local gateway",
    description=(
        "Runs on your machine. Your PDFs are indexed and searched here; only "
        "the matching snippets are sent to the answer engine."
    ),
    version="1.0.0",
)

# The React dev server, a built bundle and file:// pages all count as
# different origins, and this gateway is reachable only from this machine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "Krish AI local gateway",
        "documents_leave_this_machine": False,
        "engine": CONFIG["engine_url"],
        "store": str(HOME),
        "retrieval": cli.RETRIEVAL,
        "semantic": cli.semantic_status(),
    }


@app.get("/health")
async def health():
    engine_ok = False

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{CONFIG['engine_url']}/health")
            engine_ok = response.status_code == 200
    except Exception:
        engine_ok = False

    semantic = cli.semantic_status()

    # "initializing" is the one state the UI needs to explain to the user: the
    # app works, but the semantic half of search is still downloading.
    if semantic["state"] in {"cold", "loading"}:
        state = "initializing"
    else:
        state = "ok"

    return {
        "status": state,
        "indexed_chunks": collection().count(),
        "engine_url": CONFIG["engine_url"],
        "engine_reachable": engine_ok,
        "api_key_configured": bool(CONFIG["api_key"]),
        "retrieval": cli.RETRIEVAL,
        "semantic": semantic,
        "message": (
            "Preparing semantic search (one-time model download). "
            "Questions work now and get sharper once it finishes."
            if state == "initializing" else "Ready."
        ),
    }


# -----------------------------
# SETTINGS
# -----------------------------
class ApiKeyRequest(BaseModel):
    api_key: str


def mask_key(key: str) -> str:
    """Enough to recognise which key is stored, not enough to use it."""
    if not key:
        return ""

    return f"{key[:9]}...{key[-4:]}" if len(key) > 16 else "set"


@app.get("/settings")
async def read_settings():
    """
    What the setup screen needs to know.

    The key itself is never returned - only whether one is stored and which
    one it is, because a UI that can read a secret back is a UI that can leak
    it to anything running in the same browser.
    """
    return {
        "api_key_configured": bool(CONFIG["api_key"]),
        "api_key_masked": mask_key(CONFIG["api_key"]),
        "engine_url": CONFIG["engine_url"],
        "config_path": str(HOME / "config.json"),
    }


@app.post("/settings/api-key")
async def save_api_key(body: ApiKeyRequest):
    """
    Store the engine key on this machine.

    It is checked against the engine before being written: a typo that is
    only discovered on the user's first question looks like a broken app.
    """
    api_key = (body.api_key or "").strip()

    if not api_key:
        raise HTTPException(status_code=400, detail="An API key is required.")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{CONFIG['engine_url']}/v1/keys/me",
                headers={"X-API-Key": api_key},
            )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach the engine at {CONFIG['engine_url']}: {error}",
        )

    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=400,
            detail="The engine rejected that key. Check it and try again.",
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Engine returned {response.status_code} while checking the key.",
        )

    tenant = response.json()
    config_file = HOME / "config.json"

    try:
        stored = json.loads(config_file.read_text()) if config_file.exists() else {}
    except Exception:
        stored = {}

    stored["api_key"] = api_key
    stored.setdefault("engine_url", CONFIG["engine_url"])

    HOME.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(stored, indent=2))

    # Readable by this user only: it is a credential sitting in a home folder.
    config_file.chmod(0o600)

    # Live, so the next question works without restarting the gateway.
    CONFIG["api_key"] = api_key

    print(f"🔑 engine key saved for {tenant.get('tenant_id', 'unknown tenant')}")

    return {
        "api_key_configured": True,
        "api_key_masked": mask_key(api_key),
        "tenant_id": tenant.get("tenant_id", ""),
        "message": "Key verified against the engine and saved on this machine.",
    }


# -----------------------------
# DOCUMENTS
# -----------------------------
def clean_file_name(name: str) -> str:
    cleaned = Path(name or "").name.strip()
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", cleaned)

    if not cleaned:
        raise HTTPException(status_code=400, detail="A file name is required.")

    if len(cleaned) > 200:
        raise HTTPException(status_code=400, detail="File name is too long.")

    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"

    return cleaned


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    user_id: str = Form("test_user_01"),
):
    """Index a PDF locally. The file is read, chunked, embedded and discarded."""
    file_name = clean_file_name(file.filename or "")

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    digest = hashlib.sha256(content).hexdigest()

    with connect() as connection:
        existing = connection.execute(
            "SELECT document_id, file_name FROM documents WHERE user_id = ? AND sha256 = ?",
            (user_id, digest),
        ).fetchone()

    if existing:
        # 409 is what the React upload box listens for to show "already uploaded".
        raise HTTPException(
            status_code=409,
            detail=f"'{existing['file_name']}' is already uploaded.",
        )

    document_id = f"doc_{uuid.uuid4().hex[:12]}"
    temp_path = TMP_DIR / f"{document_id}.pdf"

    try:
        temp_path.write_bytes(content)
        chunks = cli.extract_chunks(temp_path)
    except SystemExit as error:
        raise HTTPException(status_code=500, detail=str(error))
    finally:
        temp_path.unlink(missing_ok=True)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No readable text found. A scanned PDF needs OCR before indexing.",
        )

    texts = [chunk["text"] for chunk in chunks]
    pages = max((chunk["page"] or 0) for chunk in chunks)

    stored = cli.index_chunks(
        HOME,
        ids=[f"{document_id}::{index}" for index in range(len(chunks))],
        texts=texts,
        metadatas=[
            {
                "document_id": document_id,
                "user_id": user_id,
                "file_name": file_name,
                "page": chunk["page"],
                "section": chunk["section"],
                "chunk_index": index,
            }
            for index, chunk in enumerate(chunks)
        ],
    )

    # If the model was still downloading, the keyword index is already live and
    # the semantic one catches up on its own thread. The upload returns now.
    if cli.semantic_enabled() and not stored["semantic"]:
        threading.Thread(
            target=lambda: cli.backfill_semantic(HOME, quiet=True), daemon=True
        ).start()

    try:
        with connect() as connection:
            connection.execute(
                "INSERT INTO documents (document_id, user_id, file_name, pages, "
                "total_chunks, sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (document_id, user_id, file_name, pages, len(chunks), digest, now()),
            )
    except Exception:
        # The chunks are indexed but the document is not listed, so nothing
        # could ever delete them. Take them back out.
        cli.delete_chunks(HOME, [f"{document_id}::{index}" for index in range(len(chunks))])
        raise

    print(f"📄 indexed {file_name}: {len(chunks)} chunks, {pages} pages (stayed local)")

    semantic_pending = cli.semantic_enabled() and not stored["semantic"]

    return {
        "document_id": document_id,
        "file_name": file_name,
        "pages": pages,
        "total_chunks": len(chunks),
        "semantic_pending": semantic_pending,
        "message": (
            f"{file_name} indexed on this machine: {len(chunks)} chunks from "
            f"{pages} page(s). Nothing was uploaded."
            + (" Semantic search is still initializing; you can ask questions now."
               if semantic_pending else "")
        ),
    }


@app.get("/documents")
async def list_documents(user_id: str = Query("test_user_01")):
    with connect() as connection:
        rows = connection.execute(
            "SELECT document_id, file_name, pages, total_chunks, created_at "
            "FROM documents WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()

    return {"documents": [dict(row) for row in rows]}


class RenameRequest(BaseModel):
    new_file_name: str
    user_id: str = "test_user_01"


@app.patch("/documents/{document_id}/rename")
async def rename_document(document_id: str, body: RenameRequest):
    file_name = clean_file_name(body.new_file_name)

    with connect() as connection:
        row = connection.execute(
            "SELECT document_id FROM documents WHERE document_id = ? AND user_id = ?",
            (document_id, body.user_id),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Document not found.")

        clash = connection.execute(
            "SELECT document_id FROM documents WHERE user_id = ? AND file_name = ? "
            "AND document_id != ?",
            (body.user_id, file_name, document_id),
        ).fetchone()

        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"Another document is already called '{file_name}'.",
            )

        connection.execute(
            "UPDATE documents SET file_name = ? WHERE document_id = ?",
            (file_name, document_id),
        )

    # The chunks carry the name too, so citations keep showing the new one -
    # in both stores, since either can be the one that surfaces a chunk.
    for store in (collection(), cli.get_semantic_collection(HOME)):
        stored = store.get(where={"document_id": document_id}, include=["metadatas"])
        ids = stored.get("ids") or []

        if not ids:
            continue

        updated = []

        for metadata in stored.get("metadatas") or []:
            metadata = dict(metadata or {})
            metadata["file_name"] = file_name
            updated.append(metadata)

        store.update(ids=ids, metadatas=updated)

    return {
        "message": "Document renamed.",
        "document_id": document_id,
        "file_name": file_name,
    }


@app.delete("/documents/{document_id}")
async def delete_document(document_id: str, user_id: str = Query("test_user_01")):
    with connect() as connection:
        row = connection.execute(
            "SELECT file_name FROM documents WHERE document_id = ? AND user_id = ?",
            (document_id, user_id),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Document not found.")

        connection.execute(
            "DELETE FROM documents WHERE document_id = ?", (document_id,)
        )

    found = collection().get(where={"document_id": document_id}, include=[])
    ids = found.get("ids") or []

    if ids:
        cli.delete_chunks(HOME, ids)

    return {
        "message": f"Deleted {row['file_name']} and its {len(ids)} chunks from this machine.",
        "document_id": document_id,
        "deleted_chunks": len(ids),
    }


# -----------------------------
# CHAT
# -----------------------------
class ChatRequest(BaseModel):
    query: str
    language: str = "english"
    session_id: str = "test_session_01"
    user_id: str = "test_user_01"
    document_mode: str = "single"
    document_id: Optional[str] = None
    document_ids: List[str] = []


def save_message(connection, session_id, user_id, role, content, sources=None, labels=None):
    connection.execute(
        "INSERT INTO messages (session_id, user_id, role, content, sources, "
        "source_labels, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            user_id,
            role,
            content,
            json.dumps(sources or []),
            json.dumps(labels or []),
            now(),
        ),
    )


def touch_session(connection, body: ChatRequest):
    """Create the conversation on first message, otherwise just bump it."""
    row = connection.execute(
        "SELECT session_id FROM sessions WHERE session_id = ?", (body.session_id,)
    ).fetchone()

    title = body.query.strip()

    if len(title) > 60:
        title = f"{title[:57]}..."

    if row:
        connection.execute(
            "UPDATE sessions SET updated_at = ?, document_mode = ?, document_id = ?, "
            "document_ids = ? WHERE session_id = ?",
            (
                now(),
                body.document_mode,
                body.document_id,
                json.dumps(body.document_ids or []),
                body.session_id,
            ),
        )
        return

    connection.execute(
        "INSERT INTO sessions (session_id, user_id, title, document_mode, "
        "document_id, document_ids, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            body.session_id,
            body.user_id,
            title or "Untitled Chat",
            body.document_mode,
            body.document_id,
            json.dumps(body.document_ids or []),
            now(),
            now(),
        ),
    )


def best_semantic(chunks: List[dict]):
    """
    The strongest semantic match in a result set, or None.

    None means the semantic retriever did not run - the model is still
    downloading, or retrieval is set to lexical only. There is then no score
    to judge, so neither the expansion trigger nor the relevance floor can
    fire, and both let the question through.
    """
    scores = [
        chunk["semantic_score"]
        for chunk in chunks
        if chunk.get("semantic_score") is not None
    ]

    return max(scores) if scores else None


async def expansion_terms(question: str) -> List[str]:
    """
    Expansion terms from the engine, or none.

    Every failure path returns an empty list: a slow or unreachable expansion
    must cost the user nothing but the timeout, because retrieval on the
    question alone is already the measured-best result.

    Note this sends the question to the engine *before* retrieval, so a
    question the relevance floor would have refused locally now leaves the
    machine. The documents still do not.
    """
    if QUERY_EXPANSION == "off" or not CONFIG["api_key"]:
        return []

    key = question.strip().lower()

    if key in _expansion_cache:
        return _expansion_cache[key]

    try:
        async with httpx.AsyncClient(timeout=EXPANSION_TIMEOUT) as client:
            response = await client.post(
                f"{CONFIG['engine_url']}/v1/expand",
                json={"query": question},
                headers={"X-API-Key": CONFIG["api_key"]},
            )

        if response.status_code != 200:
            return []

        terms = [str(term) for term in (response.json().get("terms") or [])]

    except Exception as error:
        print(f"⚠️  expansion skipped ({type(error).__name__}: {error})")
        return []

    if len(_expansion_cache) >= EXPANSION_CACHE_MAX:
        _expansion_cache.clear()

    _expansion_cache[key] = terms

    return terms


async def ask_engine(question: str, chunks: List[dict]) -> dict:
    """Send the question and the chosen chunks to the engine. Nothing else."""
    api_key = require_engine_key()

    payload = {
        "query": question,
        "context": [
            {
                "text": chunk["text"],
                "page": chunk.get("page"),
                "source": chunk.get("source"),
                "score": chunk.get("rank_score"),
            }
            for chunk in chunks
        ],
    }

    url = f"{CONFIG['engine_url']}/v1/ask-stateless"

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"X-API-Key": api_key},
            )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach the answer engine at {CONFIG['engine_url']}: {error}",
        )

    if response.status_code == 200:
        return response.json()

    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text

    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=response.status_code,
            detail=f"The engine rejected the API key: {detail}",
        )

    if response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="The engine is rate limiting this key. Wait a moment and retry.",
        )

    raise HTTPException(status_code=502, detail=f"Engine error: {detail}")


@app.post("/chat")
async def chat(body: ChatRequest):
    """
    Answer a question about the local documents.

    Retrieval happens here; only the top chunks travel to the engine.
    """
    question = (body.query or "").strip()

    if not question:
        raise HTTPException(status_code=400, detail="A question is required.")

    mode = body.document_mode if body.document_mode in {"single", "multiple", "all"} else "single"

    if collection().count() == 0:
        answer = "No document has been indexed yet. Upload a PDF first."

        with connect() as connection:
            touch_session(connection, body)
            save_message(connection, body.session_id, body.user_id, "user", question)
            save_message(connection, body.session_id, body.user_id, "bot", answer)

        return {
            "answer": answer,
            "grounded": False,
            "sources": [],
            "source_labels": [],
            "session_id": body.session_id,
        }

    started = time.time()

    scope = document_filter(body.user_id, mode, body.document_id, body.document_ids)

    if cli.is_document_level_question(question):
        # "Summarize this pdf" has nothing to search for. Send a spread of the
        # document instead of the chunks that share a word with the question,
        # and skip expansion: there is no topic to expand.
        chunks = cli.spread_chunks(collection(), where=scope)
    else:
        # First pass on the question alone. 46ms, and for most questions it is
        # the final answer - the expansion call costs thirty times as much.
        chunks = cli.query_store(HOME, collection(), question, TOP_K, where=scope)

        best = best_semantic(chunks)

        # Three bands. Below the floor the question is off topic and expansion
        # would only buy a slower refusal, so it is skipped and the floor check
        # further down does the refusing. Above the trigger the first pass is
        # already strong. In between is the only place expansion earns its
        # latency.
        weak = (
            best is not None
            and RELEVANCE_FLOOR <= best < EXPANSION_TRIGGER
            and QUERY_EXPANSION != "off"
        )

        if weak:
            terms = await expansion_terms(question)

            if terms:
                print(
                    f"🔎 first pass {best:.4f} < {EXPANSION_TRIGGER}, expanded: "
                    f"{', '.join(terms[:8])}"
                )

                # Same cached collection handles - no new client, no reopen.
                second = cli.query_store(
                    HOME,
                    collection(),
                    # The question is what gets scored, cited and answered.
                    # Only the search uses the extra terms.
                    question,
                    TOP_K,
                    where=scope,
                    extra_terms=terms if QUERY_EXPANSION == "augment" else None,
                    search_text=(
                        f"{question} {' '.join(terms)}"
                        if QUERY_EXPANSION == "replace"
                        else None
                    ),
                )

                if second:
                    chunks = second

    # Applied to whatever retrieval finally produced, first pass or second: an
    # expansion that lifts nothing above the floor still means the document
    # does not cover the question.
    final_best = best_semantic(chunks)
    off_topic = final_best is not None and final_best < RELEVANCE_FLOOR

    if not chunks or off_topic:
        if off_topic:
            print(
                f"🚫 off topic: best semantic {final_best:.4f} < "
                f"{RELEVANCE_FLOOR} - refused locally, engine not called"
            )

        result = {"answer": NOT_AVAILABLE, "grounded": False}
    else:
        result = await ask_engine(question, chunks)

    answer = result.get("answer") or NOT_AVAILABLE
    grounded = bool(result.get("grounded"))

    sources = []
    labels = []

    if grounded and chunks:
        for chunk in cli.cited_chunks(answer, chunks):
            sources.append({
                "file_name": chunk.get("source"),
                "page_number": chunk.get("page"),
                "chunk_index": chunk.get("chunk_index"),
            })

            label = f"{chunk.get('source')} - Page {chunk.get('page')}"

            if label not in labels:
                labels.append(label)

    with connect() as connection:
        touch_session(connection, body)
        save_message(connection, body.session_id, body.user_id, "user", question)
        save_message(
            connection,
            body.session_id,
            body.user_id,
            "bot",
            answer,
            sources,
            labels,
        )

    retrievers = sorted({
        name for chunk in chunks for name in chunk.get("found_by", [])
    })

    print(
        f"💬 {len(chunks)} chunks sent ({'+'.join(retrievers) or 'spread'}), "
        f"grounded={grounded}, {time.time() - started:.1f}s - '{question[:60]}'"
    )

    return {
        "answer": answer,
        "grounded": grounded,
        "sources": sources,
        "source_labels": labels,
        "chunks_used": len(chunks),
        "retrievers": retrievers,
        "session_id": body.session_id,
    }


@app.get("/chat-sessions")
async def chat_sessions(user_id: str = Query("test_user_01")):
    with connect() as connection:
        rows = connection.execute(
            "SELECT session_id, title, document_mode, document_id, document_ids, "
            "created_at, updated_at FROM sessions WHERE user_id = ? "
            "ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()

    sessions = []

    for row in rows:
        session = dict(row)

        try:
            session["document_ids"] = json.loads(session.get("document_ids") or "[]")
        except Exception:
            session["document_ids"] = []

        sessions.append(session)

    return {"sessions": sessions}


@app.get("/chat-history/{session_id}")
async def chat_history(session_id: str, user_id: str = Query("test_user_01")):
    with connect() as connection:
        rows = connection.execute(
            "SELECT role, content, sources, source_labels, created_at FROM messages "
            "WHERE session_id = ? AND user_id = ? ORDER BY id ASC",
            (session_id, user_id),
        ).fetchall()

    messages = []

    for row in rows:
        message = dict(row)

        for field in ("sources", "source_labels"):
            try:
                message[field] = json.loads(message.get(field) or "[]")
            except Exception:
                message[field] = []

        messages.append(message)

    return {"session_id": session_id, "messages": messages}


@app.delete("/chat-sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = Query("test_user_01")):
    with connect() as connection:
        row = connection.execute(
            "SELECT session_id FROM sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()

        deleted = connection.execute(
            "DELETE FROM messages WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        ).rowcount

        if row:
            connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )

    if not row and not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return {"message": "Conversation deleted.", "deleted_messages": deleted}


# -----------------------------
# VOICE
# -----------------------------
class TTSRequest(BaseModel):
    text: str
    language: str = "english"
    voice: Optional[str] = None


def clean_text_for_speech(text: str) -> str:
    cleaned = (text or "")

    for symbol in ("*", "#", "`", "•"):
        cleaned = cleaned.replace(symbol, "")

    cleaned = cleaned.replace("-", " ").replace("\n", ". ")
    cleaned = cleaned.replace(":", ". ").replace(";", ". ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned[:2500]


@app.post("/tts")
async def text_to_speech(body: TTSRequest = Body(...)):
    """
    Read an answer aloud.

    Note: edge-tts sends the text to Microsoft's voice service, so this is the
    one endpoint that leaves the machine with document-derived text. Turn
    auto-speak off in the UI if that matters for your deployment.
    """
    try:
        import edge_tts
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="edge-tts is not installed. Run: pip install edge-tts",
        )

    spoken = clean_text_for_speech(body.text)

    if not spoken:
        raise HTTPException(status_code=400, detail="Text is empty.")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = AUDIO_DIR / f"tts_{uuid.uuid4().hex}.mp3"

    try:
        speech = edge_tts.Communicate(
            text=spoken,
            voice=body.voice or "en-US-JennyNeural",
            rate="+0%",
        )

        await speech.save(str(audio_path))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Voice generation failed: {error}")

    if not audio_path.exists() or not audio_path.stat().st_size:
        raise HTTPException(status_code=500, detail="Voice generation produced no audio.")

    return FileResponse(audio_path, media_type="audio/mpeg", filename=audio_path.name)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
