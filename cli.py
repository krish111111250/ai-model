#!/usr/bin/env python3
"""
Krish AI - edge RAG client.

Your documents never leave this machine. The PDF is read, split and embedded
locally, stored in a ChromaDB folder under your home directory, and searched
locally. Only the handful of chunks that match your question are sent to the
engine, which turns them into an answer and keeps nothing.

    python3 cli.py add report.pdf              # index a PDF locally
    python3 cli.py ask "what is the budget"    # ask (searches locally first)
    python3 cli.py                             # interactive
    python3 cli.py list                        # what you have indexed
    python3 cli.py remove report.pdf           # delete it from the local index

Setup:
    pip install chromadb 'markitdown[pdf,docx,pptx,xlsx]'
    export KRISH_API_KEY=krish_...             # from your account dashboard

Search is hybrid: every question runs through a pure-Python TF-IDF index
(exact words, no model) and through all-MiniLM-L6-v2 running locally on
onnxruntime (meaning), and the two hit lists are fused. The model is fetched
once (~80MB) into ~/.cache/chroma and never leaves this machine. Set
KRISH_RETRIEVAL=lexical for no download at all, or =semantic for meaning only.

Where things live:
    ~/.krish/chroma/       your local vector database (never uploaded)
    ~/.krish/lexicon.json  word statistics used to weight searches
"""

import argparse
import json
import math
import os
import re
import sys
import threading
import zlib
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = os.environ.get("KRISH_API_URL", "http://localhost:8000")
DEFAULT_HOME = Path(os.environ.get("KRISH_HOME", Path.home() / ".krish"))

# How a question finds its chunks:
#   hybrid   both retrievers, results fused   (default, most accurate)
#   lexical  TF-IDF only - no model, no download
#   semantic MiniLM only
RETRIEVAL = (os.environ.get("KRISH_RETRIEVAL") or "hybrid").strip().lower()

# Vectors from different embedders are not comparable, so each gets its own
# collection. Both hold the same chunk ids, text and metadata, which is what
# lets a result from either retriever be merged with the other.
LEXICAL_COLLECTION = "krish_local_documents"
SEMANTIC_COLLECTION = "krish_local_minilm"

CHUNK_SIZE = 600
CHUNK_OVERLAP = 100

# Chunks sent to the engine after reranking. Three rather than four: measured
# on 24 questions the answer was present just as often (22/24) while 23% less
# text reached the model, and less unrelated material in the prompt is what
# stops it attaching a number from one rule to the subject of another.
TOP_K = int(os.environ.get("KRISH_TOP_K", "3"))

# Candidates pulled from each retriever before fusion. Deliberately small:
# a wide pool makes both lists overlap on most of a short document, and then
# "both retrievers agree" stops meaning anything.
CANDIDATE_MULTIPLIER = 2
MIN_CANDIDATES = 8

# Reciprocal rank fusion. The two retrievers score on scales that cannot be
# compared - a cosine of 0.42 from MiniLM means nothing next to 0.42 from
# TF-IDF - so they are merged on rank instead.
#
# k=1 keeps first place worth having: 1/(1+1) against 1/(1+2) is a real gap,
# whereas the textbook k=60 would put rank 1 and rank 5 within 6% of each
# other and let two middling hits outvote one retriever's best answer. On a
# 40-page document that cost 9 of 15 questions their correct chunk.
RRF_K = 1

# How much the keyword list counts for, decided per question - see
# lexical_weight(). Measured on a 40-page manual: for questions phrased in the
# reader's own words ("how much holiday am I entitled to" for "21 days of paid
# annual leave") the model found the answer in 14 of 15 and keywords in 7; for
# questions quoting the document the two tied at 9 of 10. So keywords are a
# specialist, and how much to trust them depends on the question.
# Expansion lists vote at this fraction of their retriever's weight.
EXPANSION_WEIGHT = 0.5

# Cross-encoder reranking. Retrieval fuses two rank lists without ever reading
# a chunk against the question; the cross-encoder reads both together, which is
# why it can tell apart two chunks that score alike.
#
# Legacy names are honoured so the RERANKER_* pair already in backend/.env
# works when exported.
RERANKER = (
    os.environ.get("KRISH_RERANKER")
    or os.environ.get("RERANKER_ENABLED")
    or "true"
).strip().lower() not in {"false", "0", "off", "no"}

RERANKER_MODEL = (
    os.environ.get("KRISH_RERANKER_MODEL")
    or os.environ.get("RERANKER_MODEL")
    or "cross-encoder/ms-marco-MiniLM-L-6-v2"
)

# How many candidates to score. Fusion is good enough to put the answer inside
# 8, and every extra pair is inference time for a chunk that was not going to
# win anyway.
RERANK_POOL = int(os.environ.get("KRISH_RERANK_POOL", "8"))

# How much a chunk is penalised per place it sat down the fusion list.
#
# Neither signal should decide alone. Pure reranking scored 21 of 24 at top-1
# but lost an answer from the top 4: asked "how long before I leave must I
# tell you", every candidate came back negative - the cross-encoder was not
# confident about any of them - and in that noise it buried the chunk fusion
# had ranked third. Pure fusion order got 19 of 24. Blending reached 22 of 24
# with nothing lost, and anything from 0.5 to 1.5 scored the same, so this is
# a plateau rather than a tuned number.
RERANK_BLEND = float(os.environ.get("KRISH_RERANK_BLEND", "0.8"))

LEXICAL_WEIGHT_NORMAL = 0.6     # ordinary wording: a junior vote
LEXICAL_WEIGHT_RARE_TERM = 1.0  # the question quotes a rare term: an equal vote
SEMANTIC_WEIGHT = 1.0

# A term in this share of the chunks or fewer counts as rare.
RARE_TERM_SHARE = 0.02

# A chunk containing every word of the question gets a small nudge. It settles
# ties without overruling either retriever.
COVERAGE_WEIGHT = 0.25

# Embedding a few hundred chunks one at a time wastes most of the model's
# throughput; the ONNX session is happiest with a batch.
EMBED_BATCH = 64


# -----------------------------
# LEXICAL EMBEDDING (no model, no download)
# -----------------------------
# A chunk becomes a vector by hashing its words into fixed slots and weighting
# them by how often they occur - classic TF-IDF, written out in plain Python.
# It matches words, not meaning, which is exactly where the semantic retriever
# is strong, and why running both beats either.
EMBED_DIM = 768

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "i",
    "if", "in", "is", "it", "its", "may", "me", "must", "not", "of", "on",
    "or", "our", "should", "so", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "to", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your",
}


def stem(word: str) -> str:
    """Crudest useful stemmer: fold plurals so 'databases' finds 'database'."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"

    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]

    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]

    return word


def tokenize(text: str):
    """Content words only, each paired with its stem."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())

    return [word for word in words if len(word) > 1 and word not in STOPWORDS]


def term_counts(text: str):
    """How much weight each hashed term gets for this text."""
    counts = {}

    for word in tokenize(text):
        counts[word] = counts.get(word, 0.0) + 1.0

        # The stem carries less weight than the word the author actually used.
        root = stem(word)

        if root != word:
            counts[root] = counts.get(root, 0.0) + 0.5

    return counts


def to_vector(weights):
    """Hash terms into slots and scale to unit length, so cosine behaves."""
    vector = [0.0] * EMBED_DIM

    for term, weight in weights.items():
        slot = zlib.crc32(term.encode()) % EMBED_DIM
        vector[slot] += weight

    length = math.sqrt(sum(value * value for value in vector))

    if not length:
        # An empty or stopword-only chunk: a zero vector would break cosine.
        vector[0] = 1.0
        return vector

    return [value / length for value in vector]


def embed_lexical_documents(texts):
    """Vectors for text being stored. Sublinear term frequency, no IDF."""
    vectors = []

    for text in texts:
        weights = {
            term: 1.0 + math.log(count)
            for term, count in term_counts(text).items()
        }
        vectors.append(to_vector(weights))

    return vectors


def embed_lexical_query(text: str, lexicon=None):
    """
    Lexical vector for a question.

    IDF is applied here rather than at indexing time, because it depends on
    the whole local corpus and that changes every time a document is added.
    Cosine against the stored vectors then ranks by rare-word overlap - a
    word like "indemnity" counts far more than "document".
    """
    lexicon = lexicon or {"chunks": 0, "df": {}}
    total = max(1, int(lexicon.get("chunks") or 0))
    document_frequency = lexicon.get("df") or {}

    weights = {}

    for term, count in term_counts(text).items():
        seen_in = int(document_frequency.get(term, 0))
        idf = math.log((1.0 + total) / (1.0 + seen_in)) + 1.0
        weights[term] = (1.0 + math.log(count)) * idf

    return to_vector(weights)


# -----------------------------
# SEMANTIC EMBEDDING (MiniLM, one-time ~80MB download)
# -----------------------------
# all-MiniLM-L6-v2 running locally through onnxruntime. It matches meaning, so
# "how much holiday do I get" finds a paragraph about annual leave that shares
# almost no words with the question. The model file is fetched once into
# ~/.cache/chroma and never leaves the machine after that.
_semantic_embedder = None
_semantic_lock = threading.Lock()
_semantic_state = {"state": "cold", "detail": "not loaded yet"}


def semantic_enabled() -> bool:
    return RETRIEVAL in {"hybrid", "semantic"}


def semantic_status() -> dict:
    """What the semantic half is doing - the UI shows this while it downloads."""
    if not semantic_enabled():
        return {"state": "disabled", "detail": f"KRISH_RETRIEVAL={RETRIEVAL}"}

    return dict(_semantic_state)


def semantic_ready() -> bool:
    return _semantic_state["state"] == "ready"


def warm_semantic(quiet: bool = False):
    """
    Load the model, downloading it the first time.

    Called on a background thread at startup so that the download happens
    while the user is still choosing a PDF, instead of inside their first
    question. Failure is not fatal: the lexical retriever answers alone.
    """
    global _semantic_embedder

    if not semantic_enabled():
        return None

    with _semantic_lock:
        if _semantic_embedder is not None:
            return _semantic_embedder

        _semantic_state.update(
            state="loading",
            detail="fetching the embedding model (~80MB, one time)",
        )

        try:
            # The model class directly, not Chroma's DefaultEmbeddingFunction
            # wrapper: the wrapper builds a fresh onnxruntime session on every
            # call, which costs ~100ms a question instead of ~22ms. Same model,
            # same weights, byte-identical vectors - just loaded once.
            try:
                from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
                    ONNXMiniLM_L6_V2,
                )

                embedder = ONNXMiniLM_L6_V2()
            except ImportError:
                from chromadb.utils import embedding_functions

                embedder = embedding_functions.DefaultEmbeddingFunction()

            # Force the download and the session start now, so "ready" means
            # ready rather than "will download on first use".
            embedder(["warm up"])

            _semantic_embedder = embedder
            _semantic_state.update(state="ready", detail="all-MiniLM-L6-v2")

            if not quiet:
                print("🧠 semantic search ready (all-MiniLM-L6-v2, local)")

        except Exception as error:
            _semantic_state.update(state="unavailable", detail=str(error))

            if not quiet:
                print(f"⚠️  semantic search unavailable, using keywords only: {error}")

        return _semantic_embedder


def embed_semantic(texts):
    """MiniLM vectors, in batches. None if the model is not available."""
    embedder = _semantic_embedder or warm_semantic()

    if embedder is None:
        return None

    vectors = []

    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]

        # tolist(), not list(): the model returns numpy rows, and list() would
        # leave a list of numpy scalars, which Chroma refuses.
        vectors += [
            vector.tolist() if hasattr(vector, "tolist") else list(vector)
            for vector in embedder(batch)
        ]

    return vectors


# -----------------------------
# CROSS-ENCODER RERANKING
# -----------------------------
_reranker = None
_reranker_state = {"state": "cold", "detail": "not loaded yet"}


def reranker_status() -> dict:
    if not RERANKER:
        return {"state": "disabled", "detail": "KRISH_RERANKER=off"}

    return dict(_reranker_state)


def reranker_ready() -> bool:
    return _reranker_state["state"] == "ready"


def warm_reranker(quiet: bool = False):
    """
    Load the cross-encoder, downloading it the first time (~88MB).

    Called on a background thread at startup for the same reason as the
    embedder: a model load has no business happening inside someone's first
    question. Failure is not fatal - retrieval keeps the fusion order.
    """
    global _reranker

    if not RERANKER:
        return None

    with _semantic_lock:
        if _reranker is not None:
            return _reranker

        _reranker_state.update(state="loading", detail=RERANKER_MODEL)

        try:
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(RERANKER_MODEL)
            model.predict([("warm", "up")])

            _reranker = model
            _reranker_state.update(state="ready", detail=RERANKER_MODEL)

            if not quiet:
                print(f"🎯 reranker ready ({RERANKER_MODEL})")

        except Exception as error:
            _reranker_state.update(state="unavailable", detail=str(error))

            if not quiet:
                print(f"⚠️  reranker unavailable, keeping fusion order: {error}")

        return _reranker


def rerank(question: str, chunks, top_k: int):
    """
    Re-order candidates by reading each one against the question.

    Retrieval ranks by similarity to a query vector; nothing in it has read a
    chunk and the question side by side. The cross-encoder does exactly that,
    which is what resolves the case fusion gets wrong: several chunks on the
    same topic, only one of which answers the question.

    Its verdict is blended with the fusion rank rather than replacing it, so a
    confident rerank can still promote the eighth candidate while an unsure
    one cannot bury the third - see RERANK_BLEND.

    Scores are kept alongside the retrieval scores rather than replacing them.
    The relevance floor is decided on the semantic score of the retrieved pool,
    so reranking cannot move that decision by dropping a chunk.
    """
    if not chunks:
        return []

    if not RERANKER or not reranker_ready() or len(chunks) <= 1:
        return chunks[:top_k]

    try:
        scores = _reranker.predict(
            [(question, chunk.get("text") or "") for chunk in chunks]
        )
    except Exception as error:
        print(f"⚠️  rerank failed, keeping fusion order: {error}")
        return chunks[:top_k]

    # Position in the incoming list is the fusion rank: query_store returned
    # these already ordered.
    for position, (chunk, score) in enumerate(zip(chunks, scores)):
        chunk["rerank_score"] = round(float(score), 4)
        chunk["blended_score"] = round(
            float(score) - RERANK_BLEND * position, 4
        )

    ranked = sorted(
        chunks, key=lambda chunk: chunk.get("blended_score", 0.0), reverse=True
    )

    return ranked[:top_k]


def lexicon_path(home: Path) -> Path:
    return home / "lexicon.json"


_lexicon_cache = {"path": None, "mtime": None, "data": None}


def load_lexicon(home: Path):
    """
    The word statistics, cached in memory.

    Every question needs them, and re-reading a few hundred KB of JSON per
    question is pure latency. The file's timestamp decides when to reload, so
    a second process adding a document is still picked up.
    """
    path = lexicon_path(home)

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"chunks": 0, "df": {}}

    if _lexicon_cache["path"] == path and _lexicon_cache["mtime"] == mtime:
        return _lexicon_cache["data"]

    try:
        data = json.loads(path.read_text())
    except Exception:
        return {"chunks": 0, "df": {}}

    _lexicon_cache.update(path=path, mtime=mtime, data=data)

    return data


def rebuild_lexicon(home: Path, collection):
    """
    Recount word statistics from whatever is currently indexed.

    Recounting is cheap at this scale (a 100-page PDF is a few hundred chunks)
    and it cannot drift out of step with the index the way incremental
    bookkeeping does after a delete.
    """
    records = collection.get(include=["documents"])
    documents = records.get("documents") or []

    document_frequency = {}

    for text in documents:
        for term in set(term_counts(text)):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    lexicon = {"chunks": len(documents), "df": document_frequency}

    home.mkdir(parents=True, exist_ok=True)
    lexicon_path(home).write_text(json.dumps(lexicon))

    return lexicon


# -----------------------------
# LOCAL STORE
# -----------------------------
_clients = {}


def get_chroma_client(home: Path):
    """One client per store path: opening it repeatedly is wasted work."""
    try:
        import chromadb
    except ImportError:
        raise SystemExit(
            "chromadb is not installed.\n  pip install chromadb markitdown"
        )

    store_path = home / "chroma"

    if store_path not in _clients:
        store_path.mkdir(parents=True, exist_ok=True)
        _clients[store_path] = chromadb.PersistentClient(path=str(store_path))

    return _clients[store_path]


def open_collection(home: Path, name: str):
    # embedding_function=None: this file computes the vectors, so Chroma never
    # downloads a model behind our back or at a moment we did not choose.
    return get_chroma_client(home).get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )


def get_collection(home: Path):
    """
    The primary collection: lexical vectors, plus every chunk's text.

    It is the source of truth for what is indexed. The semantic collection
    mirrors it and may lag behind while the model downloads.
    """
    return open_collection(home, LEXICAL_COLLECTION)


def get_semantic_collection(home: Path):
    return open_collection(home, SEMANTIC_COLLECTION)


# -----------------------------
# INDEXING
# -----------------------------
def index_chunks(home: Path, ids, texts, metadatas):
    """
    Store chunks in both retrievers.

    The lexical side is written first and always: it needs no model, so a
    question can be answered the moment the upload finishes. The semantic side
    is written too if the model is loaded, and left to backfill_semantic() if
    it is still downloading - which is what keeps an upload fast.
    """
    collection = get_collection(home)

    try:
        collection.add(
            ids=ids,
            documents=texts,
            embeddings=embed_lexical_documents(texts),
            metadatas=metadatas,
        )

        semantic_count = 0

        if semantic_enabled() and semantic_ready():
            vectors = embed_semantic(texts)

            if vectors:
                get_semantic_collection(home).add(
                    ids=ids,
                    documents=texts,
                    embeddings=vectors,
                    metadatas=metadatas,
                )
                semantic_count = len(ids)

    except Exception:
        # All of the document or none of it. A half-written document is worse
        # than a failed upload: its chunks answer questions while the document
        # itself is not listed anywhere, so nobody can see or delete it.
        delete_chunks(home, ids)
        raise

    rebuild_lexicon(home, collection)

    return {"lexical": len(ids), "semantic": semantic_count}


def backfill_semantic(home: Path, quiet: bool = False):
    """
    Give the semantic store whatever the lexical store has and it lacks.

    Comparing ids makes this self-healing: it covers chunks added while the
    model was downloading, an interrupted run, or a customer who started in
    lexical-only mode and switched to hybrid later.
    """
    if not semantic_enabled():
        return 0

    if not semantic_ready() and warm_semantic(quiet=quiet) is None:
        return 0

    collection = get_collection(home)
    semantic = get_semantic_collection(home)

    indexed = set(collection.get(include=[]).get("ids") or [])
    embedded = set(semantic.get(include=[]).get("ids") or [])

    missing = sorted(indexed - embedded)
    stale = sorted(embedded - indexed)

    if stale:
        semantic.delete(ids=stale)

    if not missing:
        return 0

    if not quiet:
        print(f"🧠 embedding {len(missing)} chunk(s) for semantic search ...")

    for start in range(0, len(missing), EMBED_BATCH):
        batch = missing[start:start + EMBED_BATCH]
        records = collection.get(ids=batch, include=["documents", "metadatas"])

        texts = records.get("documents") or []
        vectors = embed_semantic(texts)

        if not vectors:
            return start

        semantic.add(
            ids=records.get("ids") or batch,
            documents=texts,
            embeddings=vectors,
            metadatas=records.get("metadatas") or None,
        )

    return len(missing)


def delete_chunks(home: Path, ids):
    """Remove chunks from both retrievers and refresh the word statistics."""
    if not ids:
        return

    collection = get_collection(home)

    for store in (collection, get_semantic_collection(home) if semantic_enabled() else None):
        if store is None:
            continue

        try:
            store.delete(ids=ids)
        except Exception as error:
            print(f"⚠️  could not remove chunks from {store.name}: {error}")

    rebuild_lexicon(home, collection)


# -----------------------------
# PDF -> CHUNKS
# -----------------------------
def looks_like_heading(line: str) -> bool:
    text = (line or "").strip()

    if not text or len(text) > 90:
        return False

    words = text.split()

    if not words or len(words) > 12:
        return False

    if text.endswith((".", ",", ";", ":")) and not re.match(r"^\d+[.)]", text):
        return False

    letters = [c for c in text if c.isalpha()]

    if len(letters) < 3:
        return False

    numbered = bool(re.match(r"^\d+\s*[.)]\s+\S", text))
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)

    return numbered or upper_ratio > 0.8


def split_text(text: str):
    """Split on paragraph, then line, then sentence, keeping an overlap."""
    pieces = []
    remaining = (text or "").strip()

    while remaining:
        if len(remaining) <= CHUNK_SIZE:
            pieces.append(remaining)
            break

        window = remaining[:CHUNK_SIZE]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))

        if cut < CHUNK_SIZE // 3:
            cut = CHUNK_SIZE

        pieces.append(remaining[:cut].strip())
        remaining = remaining[max(0, cut - CHUNK_OVERLAP):].strip()

    return [piece for piece in pieces if piece]


# Formats MarkItDown converts. PDFs are the common case; the rest is why it
# is here at all - the previous reader handled PDFs and nothing else.
SUPPORTED_SUFFIXES = {
    ".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls", ".csv",
    ".html", ".htm", ".md", ".txt", ".json", ".xml", ".epub",
}


def extract_pages(path: Path) -> list:
    """
    A document as a list of pages, in order.

    MarkItDown returns one Markdown string for the whole file, which would
    cost the page numbers every citation is built from - "handbook.pdf -
    Page 2" is the product, not decoration. pdfminer, which it uses for PDFs,
    separates pages with a form feed, so the boundaries survive the
    conversion and the page number is the index. Verified exact on a 5-page
    and a 40-page document.

    Formats with no page concept - a spreadsheet, a web page - come back as a
    single page, which is the honest answer rather than an invented number.
    """
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise SystemExit(
            "markitdown is not installed.\n"
            "  pip install 'markitdown[pdf,docx,pptx,xlsx]'"
        )

    try:
        markdown = MarkItDown().convert(str(path)).text_content or ""
    except Exception as error:
        raise SystemExit(f"Could not read {path.name}: {error}")

    pages = markdown.split("\f")

    # A file that converted to nothing readable: a scan with no text layer.
    if not any(page.strip() for page in pages):
        return []

    return pages


def extract_chunks(document_path: Path):
    """
    Read a document and split it section by section.

    Each chunk carries its heading, so a chunk stays searchable by its topic
    even when the body never repeats it - the same approach the server used.
    """
    chunks = []
    current_section = ""

    for page_number, page_text in enumerate(extract_pages(document_path), start=1):
        text = (page_text or "").strip()

        if not text:
            continue

        blocks = []
        buffer = []

        for line in text.splitlines():
            # Markdown headings are explicit, which is better evidence than
            # the shape of a line; the old guess stays as the fallback for
            # documents that carry no heading markup.
            stripped = line.strip()
            heading = stripped.lstrip("#").strip() if stripped.startswith("#") else None

            if heading or looks_like_heading(line):
                if buffer:
                    blocks.append((current_section, "\n".join(buffer).strip()))
                    buffer = []

                current_section = heading or stripped
            else:
                buffer.append(line)

        if buffer:
            blocks.append((current_section, "\n".join(buffer).strip()))

        for heading, body in blocks:
            if not body:
                continue

            for piece in split_text(body):
                chunks.append({
                    "text": f"{heading}\n{piece}" if heading else piece,
                    "page": page_number,
                    "section": heading,
                })

    return chunks


# -----------------------------
# COMMANDS
# -----------------------------
def cmd_add(args, home: Path):
    pdf_path = Path(args.pdf).expanduser()

    if not pdf_path.exists():
        raise SystemExit(f"File not found: {pdf_path}")

    collection = get_collection(home)
    name = pdf_path.name

    existing = collection.get(where={"file_name": name}, include=[])

    if existing.get("ids"):
        if not args.replace:
            raise SystemExit(
                f"'{name}' is already indexed ({len(existing['ids'])} chunks). "
                "Use --replace to re-index it."
            )
        delete_chunks(home, existing["ids"])
        print(f"  replaced {len(existing['ids'])} existing chunks")

    print(f"Reading {name} ...")
    chunks = extract_chunks(pdf_path)

    if not chunks:
        raise SystemExit(
            "No readable text found. A scanned PDF needs OCR before indexing."
        )

    print(f"  {len(chunks)} chunks; embedding locally ...")

    texts = [chunk["text"] for chunk in chunks]

    stored = index_chunks(
        home,
        ids=[f"{name}::{i}" for i in range(len(chunks))],
        texts=texts,
        metadatas=[
            {
                "file_name": name,
                "page": chunk["page"],
                "section": chunk["section"],
                "chunk_index": index,
            }
            for index, chunk in enumerate(chunks)
        ],
    )

    if semantic_enabled() and not stored["semantic"]:
        # The model was still downloading; catch the new chunks up now.
        backfill_semantic(home)

    print(f"✅ Indexed {name}: {len(chunks)} chunks stored in {home / 'chroma'}")
    print("   Nothing was uploaded. Ask with: python3 cli.py ask \"your question\"")


def cmd_list(args, home: Path):
    collection = get_collection(home)
    records = collection.get(include=["metadatas"])
    metadatas = records.get("metadatas") or []

    if not metadatas:
        print("Nothing indexed yet. Add a PDF with: python3 cli.py add file.pdf")
        return

    counts = {}

    for metadata in metadatas:
        name = (metadata or {}).get("file_name", "unknown")
        counts[name] = counts.get(name, 0) + 1

    print(f"{len(counts)} document(s) in {home / 'chroma'}:")

    for name, count in sorted(counts.items()):
        print(f"  {name}  ({count} chunks)")


def cmd_remove(args, home: Path):
    collection = get_collection(home)
    found = collection.get(where={"file_name": args.pdf}, include=[])
    ids = found.get("ids") or []

    if not ids:
        raise SystemExit(f"'{args.pdf}' is not indexed. See: python3 cli.py list")

    delete_chunks(home, ids)
    print(f"Removed {args.pdf} ({len(ids)} chunks) from the local index.")


def keyword_coverage(question: str, text: str) -> float:
    """How many of the question's distinct content words the chunk contains."""
    wanted = {stem(word) for word in tokenize(question)}

    if not wanted:
        return 0.0

    have = {stem(word) for word in tokenize(text)}

    return len(wanted & have) / len(wanted)


def run_retriever(collection, query_vector, candidates, where=None):
    """One retriever's hit list, best first, as plain dictionaries."""
    if query_vector is None:
        return []

    try:
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=candidates,
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as error:
        print(f"⚠️  retriever failed, continuing without it: {error}")
        return []

    ids = (results.get("ids") or [[]])[0]
    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]

    hits = []

    for index, text in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else None

        hits.append({
            "id": ids[index] if index < len(ids) else f"hit_{index}",
            "text": text,
            "page": metadata.get("page"),
            "source": metadata.get("file_name"),
            "document_id": metadata.get("document_id"),
            "chunk_index": metadata.get("chunk_index"),
            "score": round(1 - distance, 4) if distance is not None else None,
        })

    return hits


def lexical_weight(question: str, lexicon) -> float:
    """
    How much to trust the keyword list for this particular question.

    Three cases, and the middle one is the reason this function exists:

    - None of the question's words appear in the document at all. The keyword
      list is then noise, and noise with a vote costs real answers: "how much
      holiday am I entitled to" shares no word with "21 days of paid annual
      leave", and the junk it matched pushed the correct chunk out of the top 4.
    - The question quotes a rare term - a code, a clause name, an unusual word.
      That is what a keyword index is for, so it votes as an equal.
    - Ordinary wording: a junior vote next to the model.
    """
    document_frequency = (lexicon or {}).get("df") or {}
    chunks = max(1, int((lexicon or {}).get("chunks") or 0))

    present = [
        document_frequency[term]
        for term in term_counts(question)
        if document_frequency.get(term)
    ]

    if not present:
        return 0.0

    if min(present) <= max(1, RARE_TERM_SHARE * chunks):
        return LEXICAL_WEIGHT_RARE_TERM

    return LEXICAL_WEIGHT_NORMAL


def fuse(question: str, rankings, top_k: int):
    """
    Merge several hit lists into one, by rank.

    A chunk both retrievers found outranks a chunk only one of them found,
    even if the one that found it was very confident - agreement between two
    methods that fail differently is the strongest signal available here. The
    same chunk arriving from both lists is one chunk, not two, so the engine
    never sees the same text twice.
    """
    merged = {}
    unit = 1.0 / (RRF_K + 1)

    for name, hits, weight in rankings:
        if not weight:
            continue


        for rank, hit in enumerate(hits, start=1):
            chunk = merged.get(hit["id"])

            if chunk is None:
                chunk = dict(hit)
                chunk["fusion_score"] = 0.0
                chunk["found_by"] = []
                merged[hit["id"]] = chunk

            chunk["fusion_score"] += weight / (RRF_K + rank)
            chunk["found_by"].append(name)
            chunk[f"{name}_rank"] = rank
            chunk[f"{name}_score"] = hit.get("score")

    for chunk in merged.values():
        coverage = keyword_coverage(question, chunk.get("text") or "")

        chunk["coverage"] = round(coverage, 4)
        chunk["rank_score"] = round(
            chunk["fusion_score"] + COVERAGE_WEIGHT * unit * coverage, 5
        )

    ranked = sorted(
        merged.values(), key=lambda chunk: chunk["rank_score"], reverse=True
    )

    return ranked[:top_k]


def query_store(
    home: Path,
    collection,
    question: str,
    top_k: int,
    where=None,
    extra_terms=None,
    search_text=None,
):
    """
    Hybrid retrieval: keywords and meaning, fused.

    The lexical retriever catches the exact term - a part number, a clause
    name, a misspelling that still shares letters. The semantic one catches
    the paragraph that answers the question in different words. Each misses
    what the other finds, so the top 4 are picked from both.
    """
    total = collection.count()

    if not total:
        return []

    candidates = min(total, max(top_k * CANDIDATE_MULTIPLIER, MIN_CANDIDATES))
    rankings = []

    # Expansion terms search as a third and fourth list beside the question's
    # own, never in place of them. Measured on a 40-page manual, replacing the
    # question lost 3 of 18 answers because a small model expands "appraisals"
    # into property valuation; fusing keeps the original's hits and adds
    # whatever the terms find on top.
    expanded = f"{question} {' '.join(extra_terms)}" if extra_terms else ""

    # "replace" mode: the expanded text is what searches, and the question is
    # kept only for scoring, citations and the answer prompt.
    searched = search_text or question

    if RETRIEVAL in {"hybrid", "lexical"}:
        lexicon = load_lexicon(home)

        # In lexical-only mode it is the only retriever, so it votes whatever
        # its weight would have been - there is nothing to be junior to.
        weight = (
            1.0 if RETRIEVAL == "lexical" else lexical_weight(searched, lexicon)
        )

        if weight:
            rankings.append((
                "lexical",
                run_retriever(
                    collection,
                    embed_lexical_query(searched, lexicon),
                    candidates,
                    where,
                ),
                weight,
            ))

    if expanded and RETRIEVAL in {"hybrid", "lexical"}:
        lexicon = load_lexicon(home)
        weight = lexical_weight(expanded, lexicon)

        if weight:
            rankings.append((
                "lexical_expanded",
                run_retriever(
                    collection,
                    embed_lexical_query(expanded, lexicon),
                    candidates,
                    where,
                ),
                # Below the question's own weight: these are a model's guess
                # at the document's wording, not the user's words.
                weight * EXPANSION_WEIGHT,
            ))

    # Never wait on the download: if the model is not loaded yet, this question
    # is answered lexically and the next one gets both.
    if semantic_enabled() and semantic_ready():
        semantic = get_semantic_collection(home)

        if semantic.count():
            vectors = embed_semantic([searched])

            rankings.append((
                "semantic",
                run_retriever(
                    semantic,
                    vectors[0] if vectors else None,
                    min(semantic.count(), candidates),
                    where,
                ),
                SEMANTIC_WEIGHT,
            ))

            if expanded:
                expanded_vectors = embed_semantic([expanded])

                if expanded_vectors:
                    rankings.append((
                        "semantic_expanded",
                        run_retriever(
                            semantic,
                            expanded_vectors[0],
                            min(semantic.count(), candidates),
                            where,
                        ),
                        SEMANTIC_WEIGHT * EXPANSION_WEIGHT,
                    ))

    if not rankings:
        # Both retrievers were skipped: the question shares no words with the
        # document and the model is not loaded yet. A weak list beats no
        # context at all, which the engine would reject outright.
        rankings.append((
            "lexical",
            run_retriever(
                collection,
                embed_lexical_query(searched, load_lexicon(home)),
                candidates,
                where,
            ),
            1.0,
        ))

    return fuse(question, rankings, top_k)


DOCUMENT_WORDS = {
    "document", "documents", "doc", "docs", "pdf", "file", "report",
    "handbook", "guide", "paper", "book",
}

OVERVIEW_WORDS = {
    "summary", "summarize", "summarise", "overview", "about", "explain",
    "content", "contents", "describe", "gist", "brief", "topic", "topics",
    "what",
}

# A summary needs breadth, so it gets more of the document than a precise
# question does - still well inside the engine's context limit.
SPREAD_K = 8


def is_document_level_question(question: str) -> bool:
    """True for "summarize this pdf" and friends: the whole document, not a topic."""
    words = set(re.findall(r"[a-z]+", (question or "").lower()))

    if {"summary", "summarize", "summarise", "overview"} & words:
        return True

    return bool(words & DOCUMENT_WORDS) and bool(words & OVERVIEW_WORDS)


def spread_chunks(collection, where=None, limit: int = SPREAD_K):
    """
    An even sample across the document, in reading order.

    "What is this document about" has no keywords to search for: the chunks
    that happen to share a word with the question tell you about one corner of
    the document. A spread tells you about the document.
    """
    records = collection.get(where=where or None, include=["documents", "metadatas"])

    documents = records.get("documents") or []
    metadatas = records.get("metadatas") or []

    items = []

    for index, text in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) else {}

        items.append({
            "text": text,
            "page": metadata.get("page"),
            "source": metadata.get("file_name"),
            "document_id": metadata.get("document_id"),
            "chunk_index": metadata.get("chunk_index"),
            "score": None,
        })

    items.sort(key=lambda chunk: (
        chunk.get("source") or "",
        chunk.get("page") or 0,
        chunk.get("chunk_index") or 0,
    ))

    if len(items) <= limit:
        return items

    step = len(items) / limit

    return [items[int(position * step)] for position in range(limit)]


def search_local(home: Path, question: str, top_k: int, file_name: str = None):
    """Search the local store. Returns the best chunks, best first."""
    collection = get_collection(home)

    if collection.count() == 0:
        raise SystemExit("Nothing indexed yet. Add a PDF with: python3 cli.py add file.pdf")

    pool = query_store(
        home,
        collection,
        question,
        RERANK_POOL if reranker_ready() else top_k,
        where={"file_name": file_name} if file_name else None,
    )

    return rerank(question, pool, top_k)


def ask_engine(url: str, api_key: str, question: str, chunks, timeout=300):
    payload = {
        "query": question,
        "context": [
            {"text": chunk["text"], "page": chunk.get("page"), "source": chunk.get("source")}
            for chunk in chunks
        ],
    }

    request = urllib.request.Request(
        url.rstrip("/") + "/v1/ask-stateless",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")

        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body

        raise SystemExit(f"Engine error {error.code}: {detail}")
    except urllib.error.URLError as error:
        raise SystemExit(f"Cannot reach {url}: {error.reason}\nIs the engine running? (./start.sh)")


def cited_chunks(answer: str, chunks, limit: int = 3):
    """
    Which chunks the answer actually came from.

    All retrieved chunks were sent, but usually only one or two were used;
    listing every page sends the reader to the wrong place.
    """
    answer_words = {
        word for word in re.findall(r"[a-z0-9]+", (answer or "").lower())
        if len(word) >= 5
    }

    if not answer_words:
        return chunks[:1]

    scored = []

    for chunk in chunks:
        chunk_words = set(re.findall(r"[a-z0-9]+", (chunk.get("text") or "").lower()))
        overlap = len(answer_words & chunk_words)

        if overlap:
            scored.append((overlap, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return chunks[:1]

    # Keep only chunks that overlap nearly as much as the best one. Without
    # this a chunk sharing one common word gets cited next to the real source.
    best = scored[0][0]
    strong = [chunk for overlap, chunk in scored if overlap >= best * 0.6]

    return strong[:limit]


def answer_question(args, home: Path, question: str):
    chunks = search_local(home, question, args.top_k, args.file)

    if args.show_context:
        print("\nLocal matches sent to the engine:")
        for chunk in chunks:
            print(f"  [{chunk['source']} p{chunk['page']} score={chunk['score']}] "
                  f"{chunk['text'][:90].replace(chr(10), ' ')}...")

    result = ask_engine(args.url, args.api_key, question, chunks)

    print()
    print(result.get("answer", "(no answer)"))

    if result.get("grounded"):
        cited = cited_chunks(result.get("answer", ""), chunks)
        pages = sorted({f"{c['source']} p{c['page']}" for c in cited if c.get("page")})

        if pages:
            print(f"\nFrom: {', '.join(pages)}")

    print()


def cmd_ask(args, home: Path):
    answer_question(args, home, args.question)


def cmd_interactive(args, home: Path):
    collection = get_collection(home)

    print(f"Krish AI - {collection.count()} chunks indexed locally in {home / 'chroma'}")
    print("Your documents stay on this machine. Ctrl-C or 'exit' to quit.\n")

    while True:
        try:
            question = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return

        if not question:
            continue

        if question.lower() in {"exit", "quit", "q"}:
            print("bye")
            return

        try:
            answer_question(args, home, question)
        except SystemExit as error:
            print(f"  {error}\n")


def main():
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Edge RAG client: your PDFs are indexed and searched locally; "
                    "only matching snippets are sent to the answer engine.",
    )
    parser.add_argument("--api-key", default=os.environ.get("KRISH_API_KEY"),
                        help="engine API key from your dashboard (or set KRISH_API_KEY)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"engine URL (default {DEFAULT_URL})")
    parser.add_argument("--home", default=str(DEFAULT_HOME),
                        help="local store location (default ~/.krish)")
    parser.add_argument("--top-k", type=int, default=TOP_K,
                        help=f"chunks to send to the engine (default {TOP_K})")
    parser.add_argument("-f", "--file", help="restrict the search to one indexed file")
    parser.add_argument("--show-context", action="store_true",
                        help="print the chunks being sent")

    sub = parser.add_subparsers(dest="command")

    add_parser = sub.add_parser("add", help="index a PDF locally")
    add_parser.add_argument("pdf")
    add_parser.add_argument("--replace", action="store_true", help="re-index if already present")
    add_parser.set_defaults(func=cmd_add, needs_key=False)

    list_parser = sub.add_parser("list", help="list locally indexed documents")
    list_parser.set_defaults(func=cmd_list, needs_key=False)

    remove_parser = sub.add_parser("remove", help="remove a document from the local index")
    remove_parser.add_argument("pdf")
    remove_parser.set_defaults(func=cmd_remove, needs_key=False)

    ask_parser = sub.add_parser("ask", help="ask a question")
    ask_parser.add_argument("question")
    ask_parser.set_defaults(func=cmd_ask, needs_key=True)

    args = parser.parse_args()
    home = Path(args.home).expanduser()

    if not args.command:
        if not args.api_key:
            parser.error("an API key is required to ask questions: --api-key or KRISH_API_KEY")

        if semantic_enabled():
            threading.Thread(target=warm_semantic, daemon=True).start()

        if RERANKER:
            threading.Thread(target=warm_reranker, daemon=True).start()

        return cmd_interactive(args, home)

    if getattr(args, "needs_key", False) and not args.api_key:
        parser.error("an API key is required to ask questions: --api-key or KRISH_API_KEY")

    # Load the models off to one side, so a question is never waiting on them.
    if getattr(args, "needs_key", False):
        if semantic_enabled():
            threading.Thread(target=warm_semantic, daemon=True).start()

        if RERANKER:
            threading.Thread(target=warm_reranker, daemon=True).start()

    return args.func(args, home)


if __name__ == "__main__":
    sys.exit(main())
