#!/usr/bin/env python3
"""
Accuracy tests for Krish AI.

Checks the three things that matter: it answers what the document contains, it
refuses what the document does not contain, and the document never leaves this
machine. Run it after changing prompts, retrieval or chunking - the numbers
tell you whether accuracy moved.

The questions go to the local gateway (port 8001), which is what the React app
talks to. The gateway retrieves locally and the engine (port 8000) only
generates, so this exercises the whole edge path end to end.

Usage:
    ./start.sh                       # services must be running
    backend/venv/bin/python tests/test_rag.py
    backend/venv/bin/python tests/test_rag.py --repeat 3   # check consistency
    backend/venv/bin/python tests/test_rag.py --keep       # leave the fixture indexed

Edit QUESTIONS below for your own document: put the page you expect in
`expect_page`, and list questions the document cannot answer in REFUSALS.
"""

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

GATEWAY = "http://localhost:8001"
ENGINE = "http://localhost:8000"

USER_ID = "test_user_01"
SESSION_ID = "accuracy_test"

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "company_handbook.pdf"

# Questions that work for ANY document.
GENERIC_QUESTIONS = [
    {"q": "what is this document about"},
    {"q": "summarize this pdf"},
]

# Per-document questions, keyed by part of the file name. Add your own here:
# "expect_page" is optional and checks the answer cites the right page.
DOCUMENT_QUESTIONS = {
    "WebDeveloper": [
        {"q": "what is web development", "expect_page": 2},
        {"q": "what is react", "expect_page": 7},
        {"q": "what is JWT", "expect_page": 12},
        {"q": "what is CSS", "expect_page": 3},
        {"q": "what is MongoDB", "expect_page": 10},
        {"q": "what is deployment", "expect_page": 14},
        {"q": "what is web devepemrnt"},    # typo on purpose
    ],
    # tests/fixtures/company_handbook.pdf - the suite indexes this itself, so
    # a clean machine can run the tests with no setup.
    "company_handbook": [
        {"q": "how many days of annual leave do I get", "expect_page": 2,
         "expect_text": "21"},
        {"q": "when must expense claims be submitted", "expect_page": 3,
         "expect_text": "30"},
        {"q": "how often are passwords rotated", "expect_page": 4,
         "expect_text": "90"},
        # The 4-hour rule belongs to tier one, not to Sev1. Both sentences sit
        # in the same chunk, so a model that merges them produces an answer
        # whose every word is in the document and whose meaning is wrong -
        # which is the one hallucination a word-level grounding check cannot
        # see. This is the guard for it.
        {"q": "what happens on a Sev1 incident", "expect_page": 5,
         "expect_text": "on-call", "reject_text": "4 hours"},
    ],
    "RAG_Complete": [
        {"q": "what is RAG", "expect_text": "retrieval-augmented generation"},
        {"q": "what is a vector database", "expect_text": "vector"},
        {"q": "what is chunking", "expect_text": "chunk"},
        {"q": "how does retrieval work", "expect_text": "retrieval"},
        {"q": "why do we need RAG", "expect_text": "rag"},
    ],
    "dhilip kumar": [
        {"q": "what is the ramani role?", "expect_page": 2,
         "expect_text": "technical lead"},
        {"q": "who is the technical lead", "expect_page": 2,
         "expect_text": "ramani"},
        # Vishal is the Project Lead; answering "Ramani ... Technical Lead"
        # here is the classic wrong-person-right-title mistake.
        {"q": "who is the project lead", "expect_page": 2,
         "expect_text": "vishal", "reject_text": "technical lead"},
        {"q": "what is swathi role", "expect_page": 2,
         "expect_text": "design thinking"},
        # The file is named "Technical Lead.pdf" but page 2 says Dhilip Kumar
        # is the "Techinal assistant" - the answer must follow the page.
        {"q": "what is dhilip kumar role", "expect_page": 2,
         "expect_text": "assistant"},
    ],
}

# Questions no uploaded document should answer.
REFUSALS = [
    "what is photosynthesis",
    "who is the prime minister of India",
    "how do I cook biryani",
    "what is quantum computing",
    "what is the price of gold today",
    "what is the author's home address",
]

REFUSAL_MARKERS = ("not available", "not in the", "no information")


# -----------------------------
# HTTP
# -----------------------------
def request_json(url, data=None, method=None, headers=None, timeout=300):
    request = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method or ("POST" if data is not None else "GET"),
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def post_file(url, path: Path, fields: dict, timeout=300):
    """Multipart upload with the standard library - no extra dependency."""
    boundary = f"----krish{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    body += path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def status_of(url, data=None, headers=None, timeout=30):
    """The status code alone, for checks where the rejection is the point."""
    try:
        request_json(url, data=data, headers=headers, timeout=timeout)
        return 200
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError):
        return 0


def ask(question, document_id):
    started = time.time()

    data = request_json(f"{GATEWAY}/chat", {
        "query": question,
        "language": "english",
        "user_id": USER_ID,
        "session_id": SESSION_ID,
        "document_mode": "single",
        "document_id": document_id,
    })

    return data, time.time() - started


def is_refusal(answer):
    lowered = (answer or "").lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


# -----------------------------
# SETUP
# -----------------------------
def ensure_document():
    """
    Pick a document to test, indexing the fixture if nothing is there.

    Indexing it here is what lets the suite run on a machine that has never
    uploaded anything - the whole point of a self-contained test.
    """
    documents = request_json(
        f"{GATEWAY}/documents?user_id={USER_ID}", timeout=30
    ).get("documents", [])

    uploaded_now = False

    if not documents:
        if not FIXTURE.exists():
            print(f"Nothing indexed and the fixture is missing: {FIXTURE}")
            sys.exit(1)

        print(f"Nothing indexed - adding {FIXTURE.name} ...")
        post_file(f"{GATEWAY}/upload", FIXTURE, {"user_id": USER_ID})
        uploaded_now = True

        documents = request_json(
            f"{GATEWAY}/documents?user_id={USER_ID}", timeout=30
        ).get("documents", [])

    document = documents[0]
    name = document["file_name"]

    print(f"Document: {name} "
          f"({document['pages']} pages, {document['total_chunks']} chunks)")

    questions = list(GENERIC_QUESTIONS)

    for key, extra in DOCUMENT_QUESTIONS.items():
        if key.lower() in name.lower():
            questions += extra
            print(f"Using the '{key}' question set.")

    if len(questions) == len(GENERIC_QUESTIONS):
        print("No question set matches this file name - running generic checks "
              "only. Add yours to DOCUMENT_QUESTIONS.")

    print()
    return document["document_id"], questions, uploaded_now


# -----------------------------
# CHECKS
# -----------------------------
def check_architecture(document_id):
    """
    The privacy promise, tested rather than asserted.

    These are cheap and they fail loudly the moment someone reintroduces
    server-side storage or drops authentication.
    """
    print("--- edge architecture")

    passed = []
    failed = []

    def record(label, problem=None):
        if problem:
            failed.append((label, problem))
            print(f"  FAIL  {label}: {problem}")
        else:
            passed.append(label)
            print(f"  ok    {label}")

    # 1. The engine refuses to answer without a key.
    body = {"query": "test", "context": ["some context text"]}
    code = status_of(f"{ENGINE}/v1/ask-stateless", data=body)
    record(
        "engine requires an API key",
        None if code == 401 else f"expected 401, got {code}",
    )

    # 2. And refuses a key it does not know.
    code = status_of(
        f"{ENGINE}/v1/ask-stateless",
        data=body,
        headers={"X-API-Key": "krish_not_a_real_key"},
    )
    record(
        "engine rejects an unknown key",
        None if code == 403 else f"expected 403, got {code}",
    )

    # 3. The engine says it stores nothing, and means it.
    try:
        root = request_json(f"{ENGINE}/", timeout=10)
        stores = root.get("stores_documents", True)
        record(
            "engine declares itself stateless",
            None if stores is False else f"stores_documents={stores}",
        )
    except Exception as error:
        record("engine declares itself stateless", str(error))

    # 4. No server-side vector store on disk.
    server_chroma = [
        path
        for path in (
            Path(__file__).resolve().parents[1] / "backend" / "app" / "chroma_db",
            Path(__file__).resolve().parents[1] / "app" / "chroma_db",
        )
        if path.exists()
    ]
    record(
        "no vector store on the server",
        None if not server_chroma else f"found {server_chroma}",
    )

    # 5. No document rows in the engine's database.
    try:
        from pymongo import MongoClient

        database = MongoClient(
            "mongodb://localhost:27017/", serverSelectionTimeoutMS=5000
        )["krish_ai_db"]

        leftovers = {
            name: database[name].count_documents({})
            for name in ("documents", "chunks", "vectors", "chat_sessions")
            if name in database.list_collection_names()
        }

        record(
            "no document rows in the engine database",
            None if not leftovers else f"found {leftovers}",
        )
    except Exception as error:
        record("no document rows in the engine database", f"check skipped: {error}")

    # 6. The gateway keeps the documents, and knows it.
    try:
        health = request_json(f"{GATEWAY}/health", timeout=10)
        problem = None

        if not health.get("indexed_chunks"):
            problem = "gateway has no local chunks"
        elif not health.get("engine_reachable"):
            problem = "gateway cannot reach the engine"

        record("gateway holds the local index", problem)
    except Exception as error:
        record("gateway holds the local index", str(error))

    print()
    return passed, failed


def run_once(document_id, questions):
    passed = []
    failed = []

    print("--- should ANSWER (in the document)")
    for case in questions:
        question = case["q"]
        data, seconds = ask(question, document_id)
        answer = data["answer"]
        cited = " ".join(data["source_labels"])

        problems = []
        if is_refusal(answer):
            problems.append("refused")
        if not data["source_labels"]:
            problems.append("no sources")
        if case.get("expect_page") and f"Page {case['expect_page']}" not in cited:
            problems.append(f"expected page {case['expect_page']}, cited {cited or 'nothing'}")
        if case.get("expect_text") and case["expect_text"].lower() not in answer.lower():
            problems.append(f"expected {case['expect_text']!r} in the answer")
        if case.get("reject_text") and case["reject_text"].lower() in answer.lower():
            problems.append(f"wrong fact: answer contains {case['reject_text']!r}")
        if len(answer.split()) < 4:
            problems.append(f"fragment, not a sentence: {answer!r}")

        label = f"{question} ({seconds:.0f}s)"
        if problems:
            failed.append((label, "; ".join(problems)))
            print(f"  FAIL  {label}: {'; '.join(problems)}")
        else:
            passed.append(label)
            print(f"  ok    {label}: {answer[:90]}")

    print("\n--- should REFUSE (not in the document)")
    for question in REFUSALS:
        data, seconds = ask(question, document_id)
        answer = data["answer"]

        problems = []
        if not is_refusal(answer):
            problems.append(f"answered instead: {answer[:80]}")
        if data["source_labels"]:
            problems.append(f"listed sources: {data['source_labels']}")

        label = f"{question} ({seconds:.0f}s)"
        if problems:
            failed.append((label, "; ".join(problems)))
            print(f"  FAIL  {label}: {'; '.join(problems)}")
        else:
            passed.append(label)
            print(f"  ok    {label}")

    return passed, failed


def cleanup(document_id):
    """Leave the machine as the suite found it."""
    try:
        request_json(
            f"{GATEWAY}/documents/{document_id}?user_id={USER_ID}",
            method="DELETE",
            timeout=60,
        )
        request_json(
            f"{GATEWAY}/chat-sessions/{SESSION_ID}?user_id={USER_ID}",
            method="DELETE",
            timeout=60,
        )
        print("Removed the test fixture and its conversation from the local store.")
    except Exception as error:
        print(f"⚠️  Could not clean up the fixture: {error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1,
                        help="run the suite N times to check consistency")
    parser.add_argument("--keep", action="store_true",
                        help="keep the fixture indexed after the run")
    args = parser.parse_args()

    for name, url in (("Gateway", GATEWAY), ("Engine", ENGINE)):
        try:
            request_json(f"{url}/health", timeout=10)
        except (urllib.error.URLError, OSError):
            print(f"{name} is not reachable on {url} - run ./start.sh first.")
            sys.exit(1)

    document_id, questions, uploaded_now = ensure_document()

    architecture_passed, architecture_failed = check_architecture(document_id)

    total_passed = 0
    total_failed = 0
    all_failures = []

    for run in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"===== run {run} of {args.repeat}")

        passed, failed = run_once(document_id, questions)
        total_passed += len(passed)
        total_failed += len(failed)
        all_failures += failed
        print()

    total = total_passed + total_failed
    architecture_total = len(architecture_passed) + len(architecture_failed)

    print(f"==== accuracy:     {total_passed}/{total} checks passed ====")
    print(f"==== architecture: {len(architecture_passed)}/{architecture_total} checks passed ====")

    all_failures += architecture_failed

    if all_failures:
        print("\nFailures:")
        for label, reason in all_failures:
            print(f"  - {label}: {reason}")

    if uploaded_now and not args.keep:
        print()
        cleanup(document_id)

    sys.exit(1 if all_failures else 0)


if __name__ == "__main__":
    main()
