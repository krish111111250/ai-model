import os
import re
import math
import uuid
import json
from datetime import datetime
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, OllamaLLM

from .database import (
    document_collection,
    chunks_collection,
    vectors_collection,
    chat_sessions_collection
)

load_dotenv()

CHROMA_PATH = os.path.join("app", "chroma_db")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
MAIN_LLM_MODEL = os.getenv("MAIN_LLM_MODEL", "llama3.2:latest")

# Cross-encoder reranker. Embedding search compares two separate vectors and
# asks "is this chunk about the same subject?"; a cross-encoder reads the
# question and the chunk together and asks "does this chunk answer THIS
# question?". It is what moves a definition above a code sample that merely
# mentions the word. Runs locally on CPU; no document text leaves the machine.
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "true").lower() not in ("0", "false", "no")

# How much of a sentence's wording must come from the retrieved text.
#   0.65 strict   - near-extractive, clipped answers, tightest grounding
#   0.40 balanced - flowing explanations, invented names/numbers still blocked
#   0.25 loose    - most natural prose, most room for the model to drift
# Invented names, numbers and counts are blocked at every setting; this only
# controls how freely the model may rephrase.
GROUNDING_MIN_RATIO = float(os.getenv("GROUNDING_MIN_RATIO", "0.4"))

embeddings = OllamaEmbeddings(
    model=EMBEDDING_MODEL,
    base_url=OLLAMA_BASE_URL
)

vector_store = Chroma(
    collection_name="krish_ai_rag",
    embedding_function=embeddings,
    persist_directory=CHROMA_PATH
)

llm = OllamaLLM(
    model=MAIN_LLM_MODEL,
    base_url=OLLAMA_BASE_URL,
    # Low temperature keeps answers close to the document instead of creative.
    temperature=0.2
)


# -----------------------------
# LANGUAGE HELPERS
# -----------------------------
def normalize_language(language: str) -> str:
    """
    Answers are English only.

    Tanglish and Tamil were removed: the local model's output in those
    languages was not accurate enough to trust, even when the facts behind it
    were correctly grounded in the document. Questions may still be typed in
    Tanglish or Tamil - see normalize_tamil_tanglish_query, which maps them to
    English for searching.
    """
    return "english"




def clean_model_output(text: str) -> str:
    if not text:
        return ""

    cleaned = str(text).strip()

    prefixes = [
        "English Answer:",
        "Tanglish Answer:",
        "Tamil Answer:",
        "Answer:",
        "Final Answer:",
        "Output:",
        "Here is the answer:",
        "Here is the Tanglish answer:",
        "Here is a Tanglish answer:",
        "Tanglish:",
        "Tamil:",
        "English:",
    ]

    for prefix in prefixes:
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix):].strip()

    cleaned = cleaned.replace("```", "")

    # Small models append notes like "(Translation: ...)" or "(Krish AI, RAG assistant)".
    cleaned = re.sub(
        r"\((?:translation|translated|note|krish ai|in english|english)[^)]*\)",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = re.split(r"\n\s*(?:translation|note|english translation)\s*:", cleaned, flags=re.IGNORECASE)[0]

    cleaned = re.sub(
        r"(?im)^\s*(?:\*\*)?(?:definition|explanation|simple explanation|answer)(?:\*\*)?\s*:\s*",
        "",
        cleaned
    )

    # Source markers copied out of the context: "[Source 2 | Page 4]", "6 | Page 1,"
    cleaned = re.sub(r"\[?\s*Source\s*\d+\s*\|[^\]]*\]?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d+\s*\|\s*Page\s*\d+\s*,?", "", cleaned, flags=re.IGNORECASE)

    # "According to the context, X is ..." -> "X is ..."
    cleaned = re.sub(
        r"(?i)\b(?:according to|as (?:stated|mentioned|described) in|based on)\s+"
        r"(?:the\s+)?(?:provided\s+)?(?:context|document|text|passage|sources?)\s*,?\s*",
        "",
        cleaned
    )
    cleaned = re.sub(
        r"(?i)\bthe\s+(?:context|document|text)\s+(?:says|states|suggests|mentions|indicates)\s+(?:that\s+)?",
        "",
        cleaned
    )

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = cleaned.strip()

    return cleaned










# -----------------------------
# FILE HELPERS
# -----------------------------
def clean_filename(file_path: str) -> str:
    """The user's own file name, without the temp prefixes we add on upload."""
    filename = os.path.basename(file_path)

    # "temp_job_3be30fe13ca9_report.pdf" -> "report.pdf"
    filename = re.sub(r"^temp_job_[0-9a-f]+_", "", filename)

    if filename.startswith("temp_"):
        filename = filename.replace("temp_", "", 1)

    return filename


# -----------------------------
# QUERY NORMALIZATION
# -----------------------------
def safe_replace_words(text: str, replacements: dict) -> str:
    result = text

    sorted_replacements = sorted(
        replacements.items(),
        key=lambda item: len(item[0]),
        reverse=True
    )

    for source_word, target_word in sorted_replacements:
        escaped_word = re.escape(source_word)

        # English/alphanumeric words should replace only as full words
        if re.match(r"^[a-zA-Z0-9 ]+$", source_word):
            pattern = r"(?<![a-zA-Z0-9])" + escaped_word + r"(?![a-zA-Z0-9])"
            result = re.sub(pattern, target_word, result, flags=re.IGNORECASE)
        else:
            result = result.replace(source_word, target_word)

    result = re.sub(r"\s+", " ", result).strip()
    return result


def normalize_tamil_tanglish_query(user_query: str) -> str:
    query = (user_query or "").lower().strip()

    filler_words = [
        "சரி", "okey", "okay", "ok", "pls", "please",
        "tell", "சொல்லு", "சொல்லுங்க", "கூறு", "கூறுங்க",
        "bro", "da", "dai", "machan", "seri", "sari",
        "sollu", "sollunga", "solunga"
    ]

    # Remove fillers only as whole words, so "da" doesn't eat "database"
    # and "ok" doesn't eat "book".
    for word in filler_words:
        pattern = r"(?<![^\s.,!?])" + re.escape(word) + r"(?![^\s.,!?])"
        query = re.sub(pattern, " ", query)

    # Standalone "ல" or "ல" suffixed to an English word ("resumeல") means "in".
    # A plain replace would corrupt Tamil words like "கல்லூரி".
    query = re.sub(r"(?<=[a-z0-9])ல(?!\S)|(?<!\S)ல(?!\S)", " in ", query)

    query = re.sub(r"\s+", " ", query).strip()

    replacements = {
        "enna": " what ",
        "ena": " what ",
        "ennanu": " what ",
        "ennatha": " what ",
        "na enna": " what is ",
        "na ena": " what is ",
        "meaning": " meaning ",
        "artham": " meaning ",
        "pathi": " about ",
        "patti": " about ",
        "ethuku": " why ",
        "edhuku": " why ",
        "use": " use ",
        "used": " used ",
        "uses": " uses ",
        "pannuvanga": " used ",
        "panna": " use ",
        "epdi": " how ",
        "eppadi": " how ",
        "evlo": " how much ",
        "evvalavu": " how much ",
        "yaaru": " who ",
        "yaru": " who ",

        "html": " html ",
        "css": " css ",
        "java script": " javascript ",
        "javascript": " javascript ",
        "js": " javascript ",
        "react": " react ",
        "node": " node ",
        "express": " express ",
        "mongodb": " mongodb ",
        "mongo db": " mongodb ",
        "database": " database ",
        "db": " database ",
        "rag": " rag ",
        "ai": " ai ",

        "ரெஸ்யூம்": " resume ",
        "ரெஸ்யூம்ல": " resume ",
        "ரெஸ்யூம் ல": " resume ",
        "resumeல": " resume ",
        "resume ல": " resume ",
        "cv": " resume ",
        "பயோடேட்டா": " resume ",

        "டாக்குமெண்ட்": " document ",
        "documentல": " document ",
        "document ல": " document ",
        "fileல": " file ",
        "file ல": " file ",

        "என்ன": " what ",
        "எது": " what ",
        "யார்": " who ",
        "எப்படி": " how ",
        "எவ்வளவு": " how much ",
        "எப்போது": " when ",
        "எங்க": " where ",
        "எங்கே": " where ",

        "நேம்": " name ",
        "name": " name ",
        "பெயர்": " name ",
        "பேர்": " name ",

        "ஸ்கில்": " skills ",
        "ஸ்கில்ஸ்": " skills ",
        "skill": " skills ",
        "skills": " skills ",
        "திறமை": " skills ",
        "திறன்கள்": " skills ",

        "எக்ஸ்பீரியன்ஸ்": " experience ",
        "experience": " experience ",
        "அனுபவம்": " experience ",

        "எஜுகேஷன்": " education ",
        "education": " education ",
        "படிப்பு": " education ",
        "கல்வி": " education ",

        "மெயில்": " email ",
        "email": " email ",
        "ஈமெயில்": " email ",

        "போன்": " phone number ",
        "phone": " phone number ",
        "mobile": " phone number ",
        "மொபைல்": " phone number ",
        "நம்பர்": " number ",

        "அட்ரஸ்": " address ",
        "address": " address ",
        "இடம்": " location ",
        "location": " location ",

        "ப்ராஜெக்ட்": " projects ",
        "project": " projects ",
        "projects": " projects ",

        "சர்டிபிகேட்": " certificates ",
        "certificate": " certificates ",
        "certificates": " certificates ",

        "ஆஃபர்": " offer ",
        "offer": " offer ",
        "offer letter": " offer letter ",

        "சம்பளம்": " salary ",
        "salary": " salary ",
        "stipend": " stipend ",
        "ஸ்டைபெண்ட்": " stipend ",

        "joining": " joining ",
        "ஜாயினிங்": " joining ",
        "role": " role ",
        "பதவி": " role ",
        "designation": " designation ",

        "இருக்கிற": " in ",
        "இருக்கும்": " in ",
        "இருக்கு": " is ",
        "உள்ள": " in ",
    }

    normalized_query = safe_replace_words(query, replacements)

    has_resume = "resume" in normalized_query
    has_document = "document" in normalized_query or "file" in normalized_query

    if has_resume and "name" in normalized_query:
        return "What is the candidate name in the resume?"

    if has_resume and "skills" in normalized_query:
        return "What skills are mentioned in the resume?"

    if has_resume and "experience" in normalized_query:
        return "What experience is mentioned in the resume?"

    if has_resume and "education" in normalized_query:
        return "What education details are mentioned in the resume?"

    if has_resume and "email" in normalized_query:
        return "What email address is mentioned in the resume?"

    if has_resume and ("phone" in normalized_query or "number" in normalized_query):
        return "What phone number is mentioned in the resume?"

    if has_resume and "address" in normalized_query:
        return "What address is mentioned in the resume?"

    if has_resume and "location" in normalized_query:
        return "What location is mentioned in the resume?"

    if has_resume and "projects" in normalized_query:
        return "What projects are mentioned in the resume?"

    if has_resume and "certificates" in normalized_query:
        return "What certificates are mentioned in the resume?"

    if has_resume:
        return "Summarize the resume."

    if "offer" in normalized_query and "salary" in normalized_query:
        return "What salary is mentioned in the offer letter?"

    if "offer" in normalized_query and "stipend" in normalized_query:
        return "What stipend is mentioned in the offer letter?"

    if "offer" in normalized_query and "joining" in normalized_query:
        return "What joining date or joining details are mentioned in the offer letter?"

    if "offer" in normalized_query and ("role" in normalized_query or "designation" in normalized_query):
        return "What role or designation is mentioned in the offer letter?"

    if "offer" in normalized_query:
        return "Summarize the offer letter."

    summary_keywords = [
        "summarize",
        "summary",
        "what this document",
        "what is in this document",
        "இந்த document என்ன",
        "இந்த டாக்குமெண்டில் என்ன",
        "என்ன சொல்ல",
    ]

    if has_document or any(keyword in query for keyword in summary_keywords):
        return "Summarize this document."

    return normalized_query if normalized_query else user_query


def translate_query_for_retrieval(user_query: str, language: str) -> str:
    try:
        selected_language = normalize_language(language)

        if selected_language == "english":
            return user_query

        rule_based_query = normalize_tamil_tanglish_query(user_query)

        print(f"🔎 Original Query: {user_query}")
        print(f"🔎 Rule-Based Retrieval Query: {rule_based_query}")

        return rule_based_query

    except Exception as e:
        print(f"⚠️ Query normalization failed, using original query: {e}")
        return user_query


# -----------------------------
# DIRECT ANSWERS - MASSIVE STYLE
# -----------------------------






# -----------------------------
# LANGUAGE CONVERSION
# -----------------------------




















# -----------------------------
# PDF EXTRACTION / STORAGE
# -----------------------------
def extract_pdf_text_with_pymupdf(file_path: str):
    try:
        import fitz
    except ImportError:
        raise ImportError(
            "PyMuPDF is not installed. Run: ./venv/bin/pip install pymupdf"
        )

    pdf_docs = []
    total_text_length = 0

    with fitz.open(file_path) as pdf:
        total_pages = len(pdf)
        print(f"📘 Total pages found: {total_pages}")

        for page_index in range(total_pages):
            page = pdf[page_index]
            text = page.get_text("text") or ""
            text = text.strip()

            print(f"📝 Page {page_index + 1} text length: {len(text)}")

            if text:
                total_text_length += len(text)

                pdf_docs.append(
                    Document(
                        page_content=text,
                        metadata={
                            "page": page_index,
                            "source": clean_filename(file_path)
                        }
                    )
                )

    print(f"🧾 Total extracted text length: {total_text_length}")

    return pdf_docs, total_text_length


HEADING_MAX_WORDS = 12


def looks_like_heading(line: str) -> bool:
    """
    Is this line a section heading?

    Covers the shapes documents actually use: "9. DATABASES - SQL & NOSQL",
    "THE TEAM", "Problem Statement". Headings are short, have no sentence
    punctuation, and are capitalised.
    """
    text = (line or "").strip()

    if not text or len(text) > 90:
        return False

    words = text.split()

    if not words or len(words) > HEADING_MAX_WORDS:
        return False

    if text.endswith((".", ",", ";", ":")) and not re.match(r"^\d+[.)]", text):
        return False

    letters = [c for c in text if c.isalpha()]

    if len(letters) < 3:
        return False

    # "9. DATABASES", "2) Overview"
    numbered = bool(re.match(r"^\d+\s*[.)]\s+\S", text))

    # "THE TEAM", "PROBLEM STATEMENT" (spaced-out capitals included)
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    shouted = upper_ratio > 0.8

    # "Problem Statement" - every significant word capitalised
    title_case = all(
        word[0].isupper() or not word[0].isalpha()
        for word in words
        if len(word) > 3
    ) and upper_ratio > 0.2

    return numbered or shouted or title_case


def split_page_into_sections(page_text: str, current_section: str):
    """Split one page into (heading, body) blocks, carrying the open section in."""
    sections = []
    heading = current_section
    buffer = []

    for line in (page_text or "").splitlines():
        if looks_like_heading(line):
            if buffer:
                sections.append((heading, "\n".join(buffer).strip()))
                buffer = []
            heading = line.strip()
        else:
            buffer.append(line)

    if buffer:
        sections.append((heading, "\n".join(buffer).strip()))

    return [(h, body) for h, body in sections if body], heading


def build_structured_chunks(documents: list) -> list:
    """
    Chunk by section, not by character count alone.

    Blind splitting cuts a section's title away from its explanation, so the
    chunk that answers "what is X" may not contain the word X at all. Here each
    chunk carries its section heading, which keeps the topic attached to the
    text and gives both BM25 and the reranker something to match.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", " ", ""]
    )

    chunks = []
    current_section = ""

    for document in documents:
        sections, current_section = split_page_into_sections(
            document.page_content, current_section
        )

        for heading, body in sections:
            for piece in splitter.split_text(body):
                piece = piece.strip()

                if not piece:
                    continue

                metadata = dict(document.metadata)
                metadata["section"] = heading or ""

                # The heading rides along with the text so a chunk is
                # searchable by its topic even when the body never repeats it.
                content = f"{heading}\n{piece}" if heading else piece

                chunks.append(Document(page_content=content, metadata=metadata))

    return chunks


LOCAL_TENANT = "local"


def process_and_store_document(
    file_path: str,
    user_id: str = "default_user",
    tenant_id: str = LOCAL_TENANT
):
    try:
        filename = clean_filename(file_path)
        legacy_temp_filename = os.path.basename(file_path)

        print(f"\n⚙️ [KRISH AI] Processing File: {filename}")

        if document_collection is not None:
            existing_doc = document_collection.find_one({
                "user_id": user_id,
                "tenant_id": tenant_id or LOCAL_TENANT,
                "$or": [
                    {"file_name": filename},
                    {"file_name": legacy_temp_filename}
                ]
            })

            if existing_doc:
                print(f"⚠️ DUPLICATE BLOCKED: '{filename}' already exists!")
                return {
                    "status": "duplicate",
                    "message": "This document is already uploaded.",
                    "chunks": 0,
                    "document_id": existing_doc.get("document_id")
                }

        documents, total_text_length = extract_pdf_text_with_pymupdf(file_path)

        if not documents or total_text_length == 0:
            return {
                "status": "no_text",
                "message": (
                    "No readable text found in this PDF. "
                    "This PDF may be scanned/image-based. "
                    "Please upload a text-based PDF, or add OCR support."
                ),
                "chunks": 0
            }

        chunks = build_structured_chunks(documents)

        if not chunks:
            # No headings found at all: fall back to plain size splitting.
            chunks = RecursiveCharacterTextSplitter(
                chunk_size=600,
                chunk_overlap=100,
                separators=["\n\n", "\n", ". ", " ", ""]
            ).split_documents(documents)

        sections = {c.metadata.get("section") for c in chunks if c.metadata.get("section")}
        print(f"📄 Document split into {len(chunks)} chunks across {len(sections)} sections.")

        if not chunks:
            return {
                "status": "no_chunks",
                "message": (
                    "Text was extracted, but no chunks were created. "
                    "Try another PDF or reduce chunk size."
                ),
                "chunks": 0
            }

        document_id = f"doc_{uuid.uuid4().hex[:8]}"

        for i, chunk in enumerate(chunks):
            page_number = chunk.metadata.get("page", 0)

            chunk.metadata.update({
                "section": chunk.metadata.get("section", ""),
                "document_id": document_id,
                "file_name": filename,
                "user_id": user_id,
                # Tenant tag. Retrieval always filters on this, so one API key
                # can never reach another key's chunks.
                "tenant_id": tenant_id or LOCAL_TENANT,
                "chunk_index": i + 1,
                "page_number": page_number + 1
            })

        ids = vector_store.add_documents(chunks)
        print(f"✅ Stored {len(ids)} chunks in ChromaDB.")

        if document_collection is not None:
            document_collection.insert_one({
                "document_id": document_id,
                "file_name": filename,
                "user_id": user_id,
                "tenant_id": tenant_id or LOCAL_TENANT,
                "pages": len(documents),
                "total_chunks": len(chunks),
                "uploaded_at": datetime.utcnow()
            })

        try:
            chroma_data = vector_store.get(
                ids=ids,
                include=["documents", "metadatas", "embeddings"]
            )

            if chunks_collection is not None:
                chunk_records = []

                for i in range(len(ids)):
                    metadata = chroma_data["metadatas"][i]

                    chunk_records.append({
                        "document_id": document_id,
                        "file_name": filename,
                        "user_id": user_id,
                        "chunk_index": metadata.get("chunk_index", i + 1),
                        "page_number": metadata.get("page_number"),
                        "text_content": chroma_data["documents"][i],
                        "created_at": datetime.utcnow()
                    })

                if chunk_records:
                    chunks_collection.insert_many(chunk_records)

            if vectors_collection is not None:
                vector_records = []

                for i in range(len(ids)):
                    embedding_vector = chroma_data["embeddings"][i]

                    vector_records.append({
                        "document_id": document_id,
                        "file_name": filename,
                        "user_id": user_id,
                        "chunk_index": i + 1,
                        "vector_array": [float(x) for x in list(embedding_vector)],
                        "created_at": datetime.utcnow()
                    })

                if vector_records:
                    vectors_collection.insert_many(vector_records)

        except Exception as mongo_sync_error:
            print("⚠️ ChromaDB stored successfully, but MongoDB mirror sync failed.")
            print(mongo_sync_error)

        return {
            "status": "success",
            "message": "Document processed and stored successfully.",
            "chunks": len(chunks),
            "document_id": document_id
        }

    except Exception as e:
        print("\n❌ CRITICAL ERROR IN RAG EXTRACTION ENGINE ❌")
        import traceback
        traceback.print_exc()
        raise e


# -----------------------------
# RAG QUERY
# -----------------------------
def normalize_document_mode(mode: str) -> str:
    selected_mode = (mode or "single").lower().strip()

    if selected_mode == "all":
        return "all"

    if selected_mode == "multiple":
        return "multiple"

    return "single"


def clean_document_ids(document_ids):
    if not document_ids:
        return []

    if not isinstance(document_ids, list):
        return []

    cleaned_ids = []

    for doc_id in document_ids:
        if doc_id and doc_id not in cleaned_ids:
            cleaned_ids.append(doc_id)

    return cleaned_ids


def get_allowed_document_ids(
    user_id: str,
    document_id: str = None,
    document_mode: str = "single",
    document_ids=None
):
    selected_mode = normalize_document_mode(document_mode)
    cleaned_ids = clean_document_ids(document_ids)

    if selected_mode == "all":
        return None

    if selected_mode == "multiple":
        return cleaned_ids

    if document_id:
        return [document_id]

    return []


def build_retriever_filter(
    user_id: str,
    document_id: str = None,
    document_mode: str = "single",
    document_ids=None,
    tenant_id: str = LOCAL_TENANT
):
    """
    The Chroma filter for one request.

    Every branch pins tenant_id. A request may only ever see chunks its own
    API key uploaded - that is the whole isolation guarantee, so it is applied
    here, once, rather than at each call site.
    """
    selected_mode = normalize_document_mode(document_mode)
    cleaned_ids = clean_document_ids(document_ids)
    tenant = tenant_id or LOCAL_TENANT

    if selected_mode == "all":
        return {
            "$and": [
                {"tenant_id": {"$eq": tenant}},
                {"user_id": {"$eq": user_id}},
            ]
        }

    if selected_mode == "multiple":
        if not cleaned_ids:
            return {"user_id": "__NO_DOCUMENT_SELECTED__"}

        return {
            "$and": [
                {"tenant_id": {"$eq": tenant}},
                {"user_id": {"$eq": user_id}},
                {"document_id": {"$in": cleaned_ids}}
            ]
        }

    if document_id:
        return {
            "$and": [
                {"tenant_id": {"$eq": tenant}},
                {"user_id": {"$eq": user_id}},
                {"document_id": {"$eq": document_id}}
            ]
        }

    return {"user_id": "__NO_DOCUMENT_SELECTED__"}


def hard_filter_retrieved_docs(
    docs,
    user_id: str,
    document_id: str = None,
    document_mode: str = "single",
    document_ids=None,
    tenant_id: str = LOCAL_TENANT
):
    selected_mode = normalize_document_mode(document_mode)
    allowed_document_ids = get_allowed_document_ids(
        user_id=user_id,
        document_id=document_id,
        document_mode=selected_mode,
        document_ids=document_ids
    )

    filtered_docs = []
    blocked_docs = []

    for doc in docs:
        metadata = doc.metadata or {}

        doc_user_id = metadata.get("user_id")
        doc_document_id = metadata.get("document_id")
        doc_file_name = metadata.get("file_name", "Unknown")

        # Chunks indexed before multi-tenancy carry no tenant_id; they belong
        # to the local (no API key) tenant.
        doc_tenant_id = metadata.get("tenant_id") or LOCAL_TENANT

        user_ok = doc_user_id == user_id and doc_tenant_id == (tenant_id or LOCAL_TENANT)

        if selected_mode == "all":
            document_ok = True
        else:
            document_ok = doc_document_id in allowed_document_ids

        if user_ok and document_ok:
            filtered_docs.append(doc)
        else:
            blocked_docs.append({
                "file_name": doc_file_name,
                "document_id": doc_document_id,
                "user_id": doc_user_id
            })

    if blocked_docs:
        print("\n🚫 [KRISH AI] BLOCKED WRONG RETRIEVED DOCS")
        for item in blocked_docs:
            print(
                f"Blocked File: {item.get('file_name')} | "
                f"Document ID: {item.get('document_id')} | "
                f"User ID: {item.get('user_id')}"
            )

    print("\n✅ [KRISH AI] FINAL ALLOWED RETRIEVED DOCS")
    for doc in filtered_docs:
        metadata = doc.metadata or {}
        print(
            f"Allowed File: {metadata.get('file_name')} | "
            f"Document ID: {metadata.get('document_id')} | "
            f"Page: {metadata.get('page_number')} | "
            f"Chunk: {metadata.get('chunk_index')}"
        )

    return filtered_docs


def get_document_name(document_id: str, user_id: str):
    if not document_id or document_collection is None:
        return None

    doc = document_collection.find_one({
        "document_id": document_id,
        "user_id": user_id
    })

    if not doc:
        return None

    return doc.get("file_name")


def get_document_names(document_ids, user_id: str):
    cleaned_ids = clean_document_ids(document_ids)

    if not cleaned_ids or document_collection is None:
        return []

    records = list(
        document_collection.find({
            "user_id": user_id,
            "document_id": {"$in": cleaned_ids}
        })
    )

    names = []

    for record in records:
        file_name = record.get("file_name")
        if file_name:
            names.append(file_name)

    return names


def get_selected_document_label(
    user_id: str,
    document_id: str = None,
    document_mode: str = "single",
    document_ids=None
):
    selected_mode = normalize_document_mode(document_mode)

    if selected_mode == "all":
        return "All uploaded documents"

    if selected_mode == "multiple":
        names = get_document_names(document_ids, user_id)

        if names:
            return ", ".join(names)

        return "Multiple selected documents"

    return get_document_name(document_id, user_id) or "Selected document"


def get_language_instruction(language: str) -> str:
    """
    Output rules for the grounded answer.

    English only. No sample answers: a small model copies facts out of examples into
    unrelated answers, which is exactly the invented detail we must avoid.
    """
    return """
OUTPUT LANGUAGE LOCK:
- Answer in English only.
- Do not use Tamil script.
- Do not use Tanglish.
- Even if user asks in Tanglish/Tamil, answer in English.
- Use clear beginner-friendly explanation.
- Use only the provided document context.
- If answer is not in context, say: "This information is not available in the selected document."
"""


def docs_to_context_text(docs) -> str:
    context_parts = []

    for index, doc in enumerate(docs, start=1):
        page_number = doc.metadata.get("page_number", "Unknown")
        text = doc.page_content

        # Deliberately no file name here. A file name is not document content,
        # and the model read it as fact: "[ dhilip kumar ] Technical Lead.pdf"
        # made it answer "Technical Lead" for Dhilip Kumar when page 2 of the
        # document actually says "Techinal assistant". Citations come from the
        # chunk metadata, so nothing is lost.
        context_parts.append(f"[Source {index} | Page {page_number}]\n{text}")

    return "\n\n".join(context_parts)


def get_empty_answer(language: str, document_mode: str = "single") -> str:
    selected_mode = normalize_document_mode(document_mode)

    if selected_mode == "all":
        return "This information is not available in the uploaded documents."

    if selected_mode == "multiple":
        return "This information is not available in the selected PDFs."

    return "This information is not available in the selected document."


# -----------------------------
# CONCEPT MISMATCH GUARD
# -----------------------------










def split_mixed_query(query: str) -> list:
    text = re.sub(r"\s+", " ", query or "").strip()

    if not text:
        return [query]

    connector_pattern = r"\bapram\b|\bapraam\b|\baprom\b|\bappram\b|\band\b|\balso\b|\bplus\b"
    rough_parts = re.split(connector_pattern, text, flags=re.IGNORECASE)

    final_parts = []

    question_marker_pattern = r"\bna enna\b|\bna ena\b|\bwhat is\b"

    for part in rough_parts:
        part = part.strip()
        if not part:
            continue

        markers = list(re.finditer(question_marker_pattern, part, flags=re.IGNORECASE))

        if len(markers) <= 1:
            final_parts.append(part)
            continue

        start = 0
        for index, marker in enumerate(markers):
            if index == len(markers) - 1:
                break

            split_at = marker.end()
            sub_part = part[start:split_at].strip()

            if len(sub_part) > 2:
                final_parts.append(sub_part)

            start = split_at

        last_part = part[start:].strip()
        if len(last_part) > 2:
            final_parts.append(last_part)

    final_parts = [p.strip() for p in final_parts if len(p.strip()) > 2]
    return final_parts if final_parts else [query]


DOCUMENT_LEVEL_QUESTION = "What is this document about? Summarize its main points."


def rewrite_subquery_for_rag(sub_query: str, language: str) -> str:
    text = re.sub(r"\s+", " ", sub_query or "").strip()

    if not text:
        return text

    if is_document_level_question(text):
        # Loose phrasings ("what the context about doc") rewrote into questions
        # the model could not parse, so it refused. Ask it plainly instead.
        return DOCUMENT_LEVEL_QUESTION

    normalized = normalize_tamil_tanglish_query(text)
    lower = f" {normalized.lower()} "

    # "vishal role means" and "what is vishal role" both ask the same thing,
    # but a small model only answers the role reliably when the question is
    # phrased "what is the role of X".
    if re.search(r"\b(role|position|designation|title)\b", lower):
        subject = re.sub(
            r"\b(role|roles|position|designation|title|means|meaning|what|whats|is|are|the|of|tell|me|about|his|her|their)\b",
            " ",
            normalized,
            flags=re.IGNORECASE
        )
        subject = re.sub(r"[^\w\s]", " ", subject)
        subject = re.sub(r"\s+", " ", subject).strip()

        if subject:
            return f"What is the role of {subject}?"

    if " what " in lower:
        topic = normalized.replace("what is", "").replace("what", "").strip()
        if topic:
            return f"What is {topic}?"

    if " how " in lower:
        return normalized

    if " about " in lower:
        topic = normalized.replace("about", "").strip()
        if topic:
            return f"What is {topic}?"

    return f"What is {normalized}?"


TOPIC_TYPO_FIXES = {
    "developemnt": "development",
    "develoment": "development",
    "devlopment": "development",
    "techer": "teacher",
    "javscript": "javascript",
    "java script": "javascript",
    "mongo db": "mongodb"
}

KEYWORD_EXPANSIONS = {
    "rag": ["rag", "retrieval augmented generation", "retrieval augmented"],
    "html": ["html", "hypertext markup language"],
    "css": ["css", "cascading style sheets"],
    "javascript": ["javascript", "java script", "js"],
    "mongodb": ["mongodb", "mongo db"],
    "ai": ["ai", "artificial intelligence"],
}

GENERIC_SINGLE_KEYWORDS = {
    "web", "developer", "development", "app", "application",
    "system", "teacher", "math", "maths", "pass"
}


def normalize_plain_for_match(text: str) -> str:
    text = (text or "").lower()

    for wrong, right in TOPIC_TYPO_FIXES.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text)

    text = text.replace("-", " ")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_query_for_match(text: str) -> str:
    text = normalize_tamil_tanglish_query(text or "")
    return normalize_plain_for_match(text)


DOCUMENT_WORDS = {
    "document", "documents", "doc", "docs", "file", "files",
    "pdf", "paper", "report", "content", "contents", "context", "text",
}

OVERVIEW_WORDS = {
    "summary", "summarize", "summarise", "overview", "about", "explain",
    "content", "contents", "context", "what", "describe", "gist", "brief",
    "topic", "topics", "detail", "details",
}


def is_document_level_question(question: str) -> bool:
    """
    True for "what is this document about", "summarize the doc", "content of
    this pdf" and similar - questions about the document as a whole rather
    than one topic inside it. These need a spread of the document, not the
    chunks that happen to share a keyword.
    """
    q = normalize_query_for_match(question)
    words = set(re.findall(r"[a-z]+", q))

    if {"summary", "summarize", "summarise", "overview"} & words:
        return True

    # e.g. "what the content about doc", "explain this pdf"
    return bool(words & DOCUMENT_WORDS) and bool(words & OVERVIEW_WORDS)


def keyword_count_in_text(keyword: str, text: str) -> int:
    text = normalize_plain_for_match(text)
    keyword = normalize_plain_for_match(keyword)

    count = 0

    patterns = KEYWORD_EXPANSIONS.get(keyword, [keyword])

    for pattern in patterns:
        pattern = normalize_plain_for_match(pattern)

        if " " in pattern:
            count += text.count(pattern)
        else:
            # Allow the plural form: the document says "databases" while the
            # question says "database", and a strict word match misses the
            # very section that explains it.
            count += len(re.findall(rf"\b{re.escape(pattern)}(?:s|es)?\b", text))

    return count






# Words a question is made of. These are never "corrected" into words from the
# document - "context" must not become "content" just because the PDF uses it.
SPELL_SKIP_WORDS = {
    # question words and verbs
    "what", "is", "are", "was", "were", "the", "this", "that", "these",
    "those", "how", "does", "did", "why", "who", "whom", "whose", "when",
    "where", "which", "about", "explain", "explains", "tell", "give", "show",
    "list", "describe", "mention", "mentioned", "says", "said", "means",
    "meaning", "summarize", "summarise", "summary", "overview", "content",
    "contents", "context", "detail", "details", "detailed", "short", "brief",
    "simple", "full", "complete", "there", "their", "have", "has", "with",
    "from", "into", "they", "them", "your", "yours", "will", "would", "can",
    "could", "should", "also", "more", "most", "some", "any", "all", "and",
    "for", "not", "but",
    # document words
    "document", "documents", "doc", "docs", "file", "files", "page", "pages",
    "pdf", "paper", "report", "text",
    # common resume/business question words
    "name", "names", "role", "roles", "title", "team", "member", "members",
    "email", "phone", "number", "address", "date", "dates", "year", "years",
    "price", "cost", "total", "skill", "skills", "experience", "education",
    "project", "projects", "company", "client", "problem", "solution",
    "feature", "features", "goal", "goals", "author", "authors",
    # Tanglish question words (questions may still be typed in Tanglish)
    "enna", "pathi", "patti", "sollu", "epdi", "eppadi", "apram", "seri",
    "panna", "pannuvanga", "ethuku", "edhuku", "yaaru", "yaru", "evlo",
}


def fetch_all_chunks(retriever_filter: dict) -> list:
    """Every chunk of the selected document(s), for keyword search and spell-check."""
    try:
        records = vector_store.get(
            where=retriever_filter,
            include=["documents", "metadatas", "embeddings"]
        )
    except Exception as e:
        print(f"⚠️ Could not load document chunks: {e}")
        return []

    texts = records.get("documents") or []
    metadatas = records.get("metadatas") or []
    embeddings_list = records.get("embeddings")

    if embeddings_list is None:
        embeddings_list = []

    chunks = []

    for i, text in enumerate(texts):
        metadata = dict(metadatas[i]) if i < len(metadatas) else {}

        if i < len(embeddings_list):
            # Kept locally only, to rank keyword hits without re-embedding.
            metadata["_embedding"] = list(embeddings_list[i])

        chunks.append(Document(page_content=text, metadata=metadata))

    return chunks


def cosine_similarity(a, b) -> float:
    if a is None or b is None or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5

    if not norm_a or not norm_b:
        return 0.0

    return dot / (norm_a * norm_b)


def get_vocabulary_from_chunks(chunks: list):
    """
    The document's words with how often each appears.

    A Counter still answers `word in vocabulary`, and the counts break ties
    when a typo is equally close to two real words ("teem" matches both "team"
    and "them"): the word the document leans on is the likelier intent.
    """
    from collections import Counter

    text = " ".join(doc.page_content or "" for doc in chunks).lower()
    return Counter(re.findall(r"[a-z][a-z0-9]+", text))


def sample_across_document(all_chunks: list, max_docs: int = 8) -> list:
    """
    An even spread of the document, start to end.

    For "what is this document about" the answer is the document itself, so
    keyword-matched chunks are the wrong input - a spread covers the whole
    thing and keeps page 1 (title, headings), which usually says what it is.
    """
    ordered = sorted(
        all_chunks,
        key=lambda doc: (
            (doc.metadata or {}).get("document_id") or "",
            (doc.metadata or {}).get("chunk_index") or 0,
        )
    )

    if len(ordered) <= max_docs:
        return ordered

    step = len(ordered) / max_docs
    picked = [ordered[min(int(i * step), len(ordered) - 1)] for i in range(max_docs)]

    # Page 1 introduces the document; keep it even if the spread skipped it.
    if picked[0] is not ordered[0]:
        picked = [ordered[0]] + picked[:-1]

    return picked


def expand_with_neighbour_chunks(docs: list, all_chunks: list, max_docs: int = 8) -> list:
    """
    Add the chunks sitting either side of each hit.

    A PDF section gets split across chunks, so the sentence naming the topic
    and the sentence explaining it often land in different chunks (the MongoDB
    definition and the MongoDB table, for example). Including the neighbours
    keeps a section whole.
    """
    by_key = {}

    for doc in all_chunks:
        meta = doc.metadata or {}
        by_key[(meta.get("document_id"), meta.get("chunk_index"))] = doc

    chosen = []
    seen = set()

    def add(doc):
        meta = doc.metadata or {}
        key = (meta.get("document_id"), meta.get("chunk_index"))

        if key in seen:
            return
        seen.add(key)
        chosen.append(doc)

    for doc in docs:
        add(doc)

    for doc in docs:
        if len(chosen) >= max_docs:
            break

        meta = doc.metadata or {}
        document_id = meta.get("document_id")
        index = meta.get("chunk_index")

        if not isinstance(index, int):
            continue

        for neighbour_index in (index - 1, index + 1):
            neighbour = by_key.get((document_id, neighbour_index))

            if neighbour is not None and len(chosen) < max_docs:
                add(neighbour)

    return chosen


_reranker = None
_reranker_failed = False


def get_reranker():
    """Load the cross-encoder once. Returns None if it is unavailable."""
    global _reranker, _reranker_failed

    if _reranker is not None or _reranker_failed or not RERANKER_ENABLED:
        return _reranker

    try:
        from sentence_transformers import CrossEncoder

        print(f"\u2699\ufe0f Loading reranker: {RERANKER_MODEL}")
        _reranker = CrossEncoder(RERANKER_MODEL)
        print("\u2705 Reranker ready")
    except Exception as e:
        # Retrieval still works without it, just less precisely.
        _reranker_failed = True
        print(f"\u26a0\ufe0f Reranker unavailable, using hybrid search order only: {e}")

    return _reranker


def rerank_documents(question: str, docs: list, limit: int = 4) -> list:
    """Order chunks by how well each one answers the question."""
    if not docs or len(docs) == 1:
        return docs[:limit]

    reranker = get_reranker()

    if reranker is None:
        return docs[:limit]

    try:
        scores = reranker.predict([(question, doc.page_content or "") for doc in docs])
    except Exception as e:
        print(f"\u26a0\ufe0f Reranking failed, keeping hybrid order: {e}")
        return docs[:limit]

    ranked = sorted(zip(docs, scores), key=lambda pair: pair[1], reverse=True)

    print("\U0001f3af Reranked: " + ", ".join(
        f"chunk {doc.metadata.get('chunk_index')}={score:.2f}"
        for doc, score in ranked[:limit]
    ))

    return [doc for doc, _ in ranked[:limit]]


def fuse_search_results(vector_docs: list, keyword_docs: list) -> list:
    """
    Combine vector and keyword results with reciprocal rank fusion: a chunk
    ranked well by either search rises to the top, and one found by both wins.
    """
    def chunk_key(doc):
        meta = doc.metadata or {}
        return f"{meta.get('document_id')}-{meta.get('chunk_index')}"

    scores = {}
    docs_by_key = {}

    for ranked_list in (vector_docs, keyword_docs):
        for rank, doc in enumerate(ranked_list):
            key = chunk_key(doc)
            docs_by_key.setdefault(key, doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (10 + rank)

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    return [docs_by_key[key] for key, _ in ordered]


def keyword_search_chunks(chunks: list, question: str, limit: int = 10) -> list:
    """
    BM25 keyword search over the whole document.

    Vector search alone can miss the one page that names the topic (embeddings
    ranked "What is MongoDB?" by overall similarity, so the comparison table
    that defines it did not make the top 25). BM25 scores a chunk by how often
    the question's words appear in it, weighted by how rare each word is in
    this document and normalised by chunk length, so a passing mention inside a
    long link list cannot outrank a short section about the topic.
    """
    keywords = get_query_keywords(question)

    if not keywords or not chunks:
        return []

    # Standard BM25 parameters: k1 controls how quickly repeated words stop
    # adding score, b how strongly long chunks are penalised.
    k1 = 1.5
    b = 0.75

    lengths = [len((doc.page_content or "").split()) or 1 for doc in chunks]
    average_length = sum(lengths) / len(lengths)
    total_chunks = len(chunks)

    # How many chunks contain each keyword, for the rarity weight.
    document_frequency = {
        keyword: sum(
            1 for doc in chunks if keyword_count_in_text(keyword, doc.page_content or "")
        )
        for keyword in keywords
    }

    scored = []

    for index, doc in enumerate(chunks):
        content = doc.page_content or ""
        length = lengths[index]
        score = 0.0

        for keyword in keywords:
            frequency = keyword_count_in_text(keyword, content)

            if not frequency:
                continue

            df = document_frequency.get(keyword) or 1
            idf = math.log(1 + (total_chunks - df + 0.5) / (df + 0.5))

            numerator = frequency * (k1 + 1)
            denominator = frequency + k1 * (1 - b + b * length / average_length)

            score += idf * numerator / denominator

        if score > 0:
            scored.append((score, index, doc))

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], item[1]))

    return [doc for _, _, doc in scored[:limit]]


def correct_spelling_with_vocabulary(query: str, vocabulary: set) -> str:
    """
    Fix typos by snapping unknown words to the closest known word.

    Candidates are the document's own words plus ordinary question words:
    "swathi rolw" has to become "swathi role" even when the document never
    uses the word "role" (it says "Design Thinking Lead"), because otherwise
    the model receives a garbled question and refuses.
    """
    if not query:
        return query

    import difflib

    candidates_pool = set(vocabulary) | SPELL_SKIP_WORDS

    if not candidates_pool:
        return query

    def fix_word(match):
        word = match.group(0)
        lower = word.lower()

        if len(lower) < 4 or lower in vocabulary or lower in SPELL_SKIP_WORDS:
            return word

        # Short words need a looser bar: "rolw" -> "role" is only a 0.75 match.
        cutoff = 0.75 if len(lower) >= 6 else 0.7
        candidates = difflib.get_close_matches(lower, candidates_pool, n=5, cutoff=cutoff)

        if not candidates:
            return word

        # Several words can be equally close ("teem" matches both "team" and
        # "them"), so prefer the one that keeps the first letter and length,
        # and prefer the document's own vocabulary over generic words.
        def candidate_rank(candidate):
            frequency = vocabulary.get(candidate, 0) if hasattr(vocabulary, "get") else 0

            return (
                candidate[:1] != lower[:1],
                abs(len(candidate) - len(lower)),
                candidate not in vocabulary,
                -frequency,
                -difflib.SequenceMatcher(None, lower, candidate).ratio(),
            )

        return sorted(candidates, key=candidate_rank)[0]

    corrected = re.sub(r"[A-Za-z]+", fix_word, query)

    if corrected != query:
        print(f"✏️ Spelling corrected: '{query}' -> '{corrected}'")

    return corrected


GREETING_WORDS = {
    "h", "hi", "hii", "hiii", "hello", "helo", "hey", "hai", "yo",
    "vanakkam", "vanakam", "வணக்கம்", "good morning", "good evening",
    "good afternoon", "thanks", "thank you", "thx", "nandri", "நன்றி",
}


def get_greeting_answer(user_query: str, language: str = "english"):
    text = re.sub(r"[^\w\s஀-௿]", "", (user_query or "").lower()).strip()

    if text not in GREETING_WORDS:
        return None

    is_thanks = text in {"thanks", "thank you", "thx", "nandri", "நன்றி"}

    if is_thanks:
        return "You're welcome! Ask me anything else about your document."
    return "Hi! I'm Krish AI. Ask me anything about your selected document."


# Words that only ask for more of the previous answer, with no topic of their own.
FOLLOWUP_ONLY_WORDS = {
    "fully", "full", "explain", "explaination", "explanation", "detail",
    "detailed", "details", "more", "elaborate", "continue", "again",
    "further", "expand", "deep", "deeper", "clearly", "clear", "brief",
    "briefly", "short", "simple", "simply", "okey", "okay", "tell", "say",
}

# Words that point back at something already discussed.
REFERENCE_WORDS = {
    "that", "this", "it", "its", "they", "them", "those", "these", "there",
    "their", "same", "above", "previous",
}


def get_previous_turn(session_id: str, user_id: str):
    """The last question and answer in this chat, used to resolve follow-ups."""
    if chat_sessions_collection is None:
        return None

    try:
        record = chat_sessions_collection.find_one(
            {"session_id": session_id, "user_id": user_id},
            sort=[("timestamp", -1)]
        )
    except Exception as e:
        print(f"\u26a0\ufe0f Could not read chat history: {e}")
        return None

    if not record:
        return None

    return {
        "query": record.get("resolved_query") or record.get("query", ""),
        "answer": record.get("answer", ""),
    }


def is_followup_question(question: str) -> bool:
    """
    True when a question only makes sense after the previous one.

    "fully explain to me" and "what the student doing in that" have no topic
    of their own - answering them standalone returns "not available" or picks
    a random part of the document.
    """
    # "what is THIS document about" points at the document, not at the previous
    # answer, so it must never borrow the last question's topic.
    if is_document_level_question(question):
        return False

    words = set(re.findall(r"[a-z]+", (question or "").lower()))
    keywords = get_query_keywords(question)

    if not keywords:
        return True

    if all(keyword in FOLLOWUP_ONLY_WORDS for keyword in keywords):
        return True

    # "what about that", "what the student doing in that"
    return bool(words & REFERENCE_WORDS) and len(keywords) < 3


def resolve_followup_question(question: str, previous_turn) -> str:
    """Carry the previous question's topic into a follow-up."""
    if not previous_turn or not previous_turn.get("query"):
        return question

    if not is_followup_question(question):
        return question

    merged = f"{previous_turn['query']} {question}".strip()
    print(f"\U0001f517 Follow-up resolved: '{question}' -> '{merged}'")
    return merged


def retrieve_for_subquery(sub_query: str, retriever_filter: dict, search_k: int, selected_language: str):
    retrieval_query = translate_query_for_retrieval(sub_query, selected_language)

    raw_docs = vector_store.similarity_search(
        retrieval_query,
        k=search_k,
        filter=retriever_filter
    )

    return raw_docs, retrieval_query


def get_answer_length_instruction(user_query: str) -> str:
    query = (user_query or "").lower()

    short_words = [
        "short",
        "brief",
        "one line",
        "oneline",
        "simple answer",
        "quick",
        "surukama",
        "short ah",
        "konjam",
    ]

    detail_words = [
        "detail",
        "detailed",
        "full",
        "explain",
        "complete",
        "deep",
        "clear ah",
        "full explanation",
    ]

    if any(word in query for word in short_words):
        return """
ANSWER LENGTH:
- Give a short answer only.
- Maximum 2 sentences.
- No bullet points.
- Direct definition first.
"""

    if any(word in query for word in detail_words):
        return """
ANSWER LENGTH:
- Give a thorough, detailed explanation of 6 to 10 sentences.
- Walk through it step by step, covering everything the context says.
- Write flowing prose, not clipped fragments.
"""

    return """
ANSWER LENGTH:
- Give a complete, well-explained answer of 4 to 7 sentences.
- Direct answer first, then the supporting detail from the context.
- Write flowing prose, not clipped fragments or bullet points.
"""


GROUNDING_COMMON_WORDS = {
    "the", "and", "for", "with", "that", "this", "these", "those", "from",
    "into", "used", "uses", "using", "use", "can", "you", "your", "are",
    "was", "were", "will", "also", "such", "like", "when", "where", "which",
    "what", "how", "why", "who", "its", "it", "is", "of", "to", "in", "on",
    "a", "an", "be", "as", "by", "or", "at", "not", "but", "they", "them",
    "there", "their", "then", "than", "other", "more", "most", "some", "all",
    "one", "two", "three", "it's", "e", "g", "i", "example", "means", "make",
    "makes", "made", "get", "gets", "help", "helps", "need", "needs", "user",
    "users", "way", "ways", "different", "simple", "easy", "important",
    # Linking words a flowing explanation is built from. They start sentences,
    # so without this they look like proper nouns and the sentence is dropped.
    "specifically", "additionally", "overall", "essentially", "importantly",
    "furthermore", "moreover", "however", "therefore", "finally", "generally",
    "typically", "basically", "ultimately", "instead", "together", "because",
    "although", "while", "since", "both", "each", "every", "this", "these",
    "together", "meanwhile", "consequently", "similarly", "likewise", "rather",
    "often", "usually", "always", "never", "sometimes", "mainly", "mostly",
}


NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "first", "second", "third", "fourth", "fifth",
    "single", "double", "triple", "both", "several", "dozen",
}


def find_unsupported_specifics(answer: str, context_text: str) -> list:
    """Names, numbers and technical terms in the answer that the document never mentions."""
    context = normalize_plain_for_match(context_text)
    context_words = set(re.findall(r"[a-z0-9.+#]+", context))

    unsupported = []

    # Counts stated as words are invented just as often as digits: the model
    # said "three students" where the document lists four team members.
    for token in re.findall(r"[A-Za-z]+", answer):
        lower = token.lower()

        if lower in NUMBER_WORDS and lower not in context_words:
            unsupported.append(token)

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#]*|\d[\d,.%]*", answer)

    for position, token in enumerate(tokens):
        lower = token.lower().strip(".,")

        if not lower or lower in GROUNDING_COMMON_WORDS or lower in context_words:
            continue

        # Only judge things a document would state literally: numbers, and
        # names/technical terms (capitalised mid-sentence or containing digits).
        is_number = bool(re.match(r"^\d", lower))

        # The first word of a sentence is capitalised by grammar, not because
        # it is a name - "Specifically, RAG solves..." must not be flagged.
        sentence_start = position == 0
        shouted = token.isupper() and len(token) > 1
        has_digit = any(c.isdigit() for c in token)

        is_name_like = has_digit or shouted or (token[:1].isupper() and not sentence_start)

        if not (is_number or is_name_like):
            continue

        if lower in context:
            continue

        unsupported.append(token)

    return unsupported


def sentence_support_ratio(sentence: str, context_words: set, context: str = "") -> float:
    """How much of a sentence's meaningful vocabulary appears in the document."""
    words = [
        w for w in re.findall(r"[a-z0-9.+#]+", normalize_plain_for_match(sentence))
        if len(w) >= 4 and w not in GROUNDING_COMMON_WORDS
    ]

    if not words:
        return 1.0

    def supported(word):
        # Substring match so "database" counts against the document's
        # "databases", and vice versa.
        return word in context_words or (context and word in context)

    return sum(1 for w in words if supported(w)) / len(words)


def select_source_docs(answer: str, context_docs: list, limit: int = 3) -> list:
    """
    Cite the chunks the answer actually came from.

    The retrieved chunks are not all used: the answer usually comes from one
    section, so citing every search hit sends the user to the wrong page.
    Each chunk is scored by how much of the answer's wording it contains.
    """
    if not answer or not context_docs:
        return []

    answer_words = {
        w for w in re.findall(r"[a-z0-9.+#]+", normalize_plain_for_match(answer))
        if len(w) >= 4 and w not in GROUNDING_COMMON_WORDS
    }

    if not answer_words:
        return context_docs[:1]

    scored = []

    for doc in context_docs:
        chunk_text = normalize_plain_for_match(doc.page_content or "")
        overlap = sum(1 for w in answer_words if w in chunk_text)

        if overlap:
            scored.append((overlap / len(answer_words), doc))

    scored.sort(key=lambda item: item[0], reverse=True)

    return [doc for _, doc in scored[:limit]] or context_docs[:1]


def answer_addresses_question(question: str, answer: str) -> bool:
    """
    Is the answer about the thing that was asked?

    With a looser wording filter the model sometimes answers a different part
    of the retrieved text: "what is the author's home address" came back with
    a paragraph about Answer Faithfulness, because the document mentions
    "addresses the limitations". Requiring the question's own subject words to
    appear in the answer catches that without constraining phrasing.
    """
    keywords = get_query_keywords(question)

    if not keywords or not answer:
        return True

    for keyword in keywords:
        if keyword_count_in_text(keyword, answer):
            return True

    print(f"🚫 Answer rejected - does not mention {keywords}: {answer[:80]}")
    return False


def keep_only_grounded_sentences(answer: str, context_text: str, min_ratio: float = None) -> str:
    """
    Remove sentences the document does not support, without policing style.

    Two different things can go wrong in a generated answer:

    1. Invented specifics - a name, number, acronym or product the document
       never mentions ("JWT is URL-safe", "MongoDB uses Object Data Modeling").
       These are real hallucinations and are always removed.
    2. Paraphrase - the same facts in the model's own words. This is what makes
       an explanation readable, and it used to be deleted too, because the
       filter demanded 65% of a sentence's vocabulary appear in the document.
       That is why answers came out clipped and rigid.

    So specifics are checked strictly, and wording is only checked loosely:
    the ratio now just catches a sentence that has drifted off the document
    entirely.
    """
    if not answer or not context_text:
        return ""

    if min_ratio is None:
        min_ratio = GROUNDING_MIN_RATIO

    context = normalize_plain_for_match(context_text)
    context_words = set(re.findall(r"[a-z0-9.+#]+", context))

    kept = []

    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
        sentence = sentence.strip()

        if not sentence:
            continue

        unsupported = find_unsupported_specifics(sentence, context_text)

        if unsupported:
            print(f"🚫 Dropped sentence - not in document {unsupported[:4]}: {sentence[:80]}")
            continue

        ratio = sentence_support_ratio(sentence, context_words, context)

        if ratio < min_ratio:
            print(f"🚫 Dropped sentence - only {ratio:.0%} from document: {sentence[:80]}")
            continue

        kept.append(sentence)

    return " ".join(kept).strip()


def generate_summary_from_context(context_text: str, fallback_line: str) -> str:
    """
    Answer "what is this document about".

    The normal answer prompt refuses here: its rules tell the model to answer
    one exact thing and not to mention other topics, which is the opposite of
    a summary, so it replied NOT_IN_DOCUMENT. A summary also cannot "not be in
    the document" - the extract IS the document.
    """
    prompt = f"""
The DOCUMENT EXTRACT below comes from a document the user uploaded.

Say what this document is about, in 3 to 6 short sentences.

RULES:
- Use ONLY what is in the DOCUMENT EXTRACT.
- Reuse its own words, names and terms. Do not introduce outside vocabulary.
- Do NOT invent facts, numbers or names that are not in the extract.
- Do NOT describe the extract itself ("this text contains..."). Describe the
  document's subject and main points.
- Plain sentences. No headings, labels or bullet markers.

DOCUMENT EXTRACT:
{context_text}

WHAT THIS DOCUMENT IS ABOUT:
"""

    answer = clean_model_output(llm.invoke(prompt)).strip()

    if not answer or "NOT_IN_DOCUMENT" in answer.upper():
        return fallback_line

    # A summary restates a whole document in a few lines, so very little of its
    # wording is shared with any one passage; invented names and numbers are
    # still blocked by the specifics check.
    grounded = keep_only_grounded_sentences(answer, context_text, min_ratio=0.25)

    return grounded or fallback_line


def generate_answer_from_context(
    sub_query: str,
    context_text: str,
    language: str,
    original_user_query: str = "",
    fallback_line: str = ""
) -> str:
    if is_document_level_question(sub_query):
        return generate_summary_from_context(context_text, fallback_line)

    length_instruction = get_answer_length_instruction(original_user_query or sub_query)

    language_instruction = get_language_instruction("english")

    prompt = f"""
You are Krish AI, a strict document-only RAG assistant.

The CONTEXT below was already retrieved from the user's selected document and
is relevant to the QUESTION. Answer the QUESTION using ONLY this CONTEXT.

GROUNDING RULES (absolute):
- Every fact, name, number, date and technical term must come from the CONTEXT.
- Never add knowledge from outside the CONTEXT, however certain you are of it.
- Never state a count or total unless the CONTEXT states that number.
- Report only what the CONTEXT states. Do not infer, conclude, or combine two
  separate statements into a new claim. That a technique was introduced by
  someone does not tell you who wrote this document.
- If the CONTEXT is merely related to the QUESTION but does not actually answer
  it, reply with exactly: NOT_IN_DOCUMENT
- If the CONTEXT does not answer the QUESTION, reply with exactly: NOT_IN_DOCUMENT

WRITING RULES:
- Explain in your own words. You may rephrase, connect and organise the
  CONTEXT's facts into a flowing explanation - you are not limited to copying
  its wording. Rewriting is encouraged; inventing is not.
- Be comprehensive: cover every part of the CONTEXT that bears on the question,
  not just the first sentence that matches.
- Write a complete, professional explanation a beginner can follow.
- Write as if you know the subject. Never mention the context, the document,
  the sources or yourself: no "according to the context", no "the document
  says", no "the CONTEXT suggests".
- Never copy the "[Source 2 | Page 4]" markers or page numbers from the CONTEXT
  into your answer.
- Never answer in a single sentence. Give at least three sentences unless the
  QUESTION explicitly asks for a short answer: state the answer, explain how
  it works, and add what the CONTEXT says about its purpose or effect.
- Do NOT say "according to the context" or "context-la".
- Answer ONLY the exact thing the QUESTION asks about.
- The CONTEXT may contain several different topics sitting close together. Use ONLY the part that directly answers the QUESTION.
- Do NOT list, define, or mention other topics from the CONTEXT that the QUESTION did not ask about.
- Open with one sentence that answers the question directly, then develop it:
  the details, how it works, and why it matters - all from the CONTEXT.
- Write complete, professional sentences. Never answer with a bare phrase, a
  heading, a table row or a fragment: "Technical Lead" is not an answer,
  "Ramani Krishnan is the Technical Lead." is.
- The CONTEXT is extracted from a PDF, so it contains layout fragments and
  run-together headings. Rewrite what you use into proper sentences instead of
  copying those fragments.
- Do not repeat the question back, and do not add headings or labels like
  "Definition:" or "Explanation:".

{length_instruction}

{language_instruction}

CONTEXT:
{context_text}

QUESTION:
{sub_query}

FINAL ANSWER:
"""

    answer = llm.invoke(prompt)
    answer = clean_model_output(answer)
    answer = (answer or "").strip()

    if not answer or "NOT_IN_DOCUMENT" in answer.upper():
        return fallback_line

    if is_answer_a_fallback(answer, fallback_line):
        return fallback_line

    # Last gate: nothing reaches the user unless the document supports it.
    grounded = keep_only_grounded_sentences(answer, context_text)

    # "RETRAINING LAG" is a heading, not an answer: when the gate leaves only
    # a fragment, try the extractive route as well and keep the fuller result.
    # When the user asked to "explain fully", one surviving sentence is also
    # too thin, so the bar is higher there.
    wants_detail = "detailed answer" in length_instruction.lower()
    minimum_words = 30 if wants_detail else 6

    too_short = len(grounded.split()) < minimum_words and len(grounded) < 300

    if not grounded or too_short:
        # The model paraphrased with its own vocabulary and every sentence was
        # dropped, or only a fragment survived. Ask once more for an extractive
        # answer: the document may well hold the answer in its own words.
        extractive_prompt = f"""
Answer the QUESTION using ONLY words and phrases copied from the CONTEXT.

RULES:
- Copy the wording from the CONTEXT. You may join or shorten its sentences.
- Do NOT add explanations, comparisons or vocabulary of your own.
- Do NOT use knowledge from outside the CONTEXT.
- If the CONTEXT does not answer the QUESTION, reply with exactly: NOT_IN_DOCUMENT

CONTEXT:
{context_text}

QUESTION:
{sub_query}

ANSWER (document's own words):
"""
        answer = clean_model_output(llm.invoke(extractive_prompt)).strip()

        if not answer or "NOT_IN_DOCUMENT" in answer.upper():
            return grounded or fallback_line

        extracted = keep_only_grounded_sentences(answer, context_text)

        # Keep whichever survived the document check with more to say.
        if len(extracted.split()) > len(grounded.split()):
            grounded = extracted

    answer = grounded

    if not answer:
        return fallback_line

    if not answer_addresses_question(sub_query, answer):
        return fallback_line

    return answer


def get_query_keywords(text: str) -> list:
    q = normalize_query_for_match(text)

    q = re.sub(
        r"\b(what is|what are|what does|what do|how to|how does|how do|tell me about|explain|definition of|meaning of)\b",
        " ",
        q
    )

    stopwords = {
        "what", "is", "are", "the", "a", "an", "how", "to", "in", "on",
        "about", "use", "used", "uses", "why", "who", "when", "where",
        "of", "this", "that", "it", "its", "be", "been", "being",
        "tell", "show", "give", "explain", "find", "get", "describe",
        "say", "please", "can", "you", "me", "my", "your", "do", "does",
        "did", "na", "enna", "eppadi", "epdi", "la", "nu", "sollu",
        "oru", "agarathu", "aagurathu", "agurathu", "become", "pass",
        "pathi", "and", "or", "for", "apram", "apraam", "seri", "idhu",
        "create", "make", "build"
    }

    words = re.findall(r"[a-zA-Z0-9]+", q)
    keywords = []

    for word in words:
        if word in stopwords:
            continue

        if len(word) < 2:
            continue

        if word not in {"css", "js"} and word.endswith("s") and len(word) > 4:
            word = word[:-1]

        keywords.append(word)

    return list(dict.fromkeys(keywords))


def filter_relevant_docs_for_question(question: str, docs: list, limit: int = 6) -> list:
    """
    Order the retrieved chunks by how well they match the question, and drop
    the ones that match nothing.

    This used to require EVERY keyword in the same chunk, which threw away the
    answer whenever the document words it differently: "what is the ramani
    role?" needs the chunk that says "[ Ramani krishnan ] Technical Lead",
    which contains "ramani" but never the word "role". Matching any keyword is
    safe here because keep_only_grounded_sentences still blocks anything the
    document does not support.
    """
    if is_document_level_question(question):
        return docs[:6]

    keywords = get_query_keywords(question)

    if not keywords:
        return docs[:4]

    def defines_keyword(content):
        for keyword in keywords:
            for pattern in KEYWORD_EXPANSIONS.get(keyword, [keyword]):
                if re.search(
                    rf"\b{re.escape(pattern)}(?:\.js)?\s+(?:is|are|means|refers to)\b",
                    content,
                    flags=re.IGNORECASE
                ):
                    return True
        return False

    scored = []

    for order, doc in enumerate(docs):
        content = doc.page_content or ""

        matched_count = 0
        total_hits = 0

        for keyword in keywords:
            hits = keyword_count_in_text(keyword, content)

            if hits > 0:
                matched_count += 1
                total_hits += hits

        if not matched_count:
            continue

        # A single generic word ("web", "app") must appear more than once
        # before a chunk counts as being about it.
        if len(keywords) == 1 and keywords[0] in GENERIC_SINGLE_KEYWORDS and total_hits < 2:
            continue

        scored.append({
            "doc": doc,
            "coverage": matched_count / len(keywords),
            "defines": defines_keyword(content),
            "order": order,
        })

    # Most keywords matched first, then chunks that define the topic, then the
    # retriever's own order (already similarity-ranked).
    scored.sort(key=lambda item: (
        -item["coverage"],
        not item["defines"],
        item["order"],
    ))

    return [item["doc"] for item in scored[:limit]]


def is_answer_a_fallback(answer: str, fallback_line: str) -> bool:
    """Fuzzy check if LLM returned the fallback (handles paraphrasing)."""
    if not answer:
        return True

    answer_lower = answer.strip().lower()
    fallback_lower = fallback_line.strip().lower()

    # Exact match
    if answer_lower == fallback_lower:
        return True

    # Answer contains fallback
    if fallback_lower in answer_lower:
        return True

    # Common fallback indicators
    fallback_indicators = [
        "kidaikkala",
        "kidaikala",
        "kidaikkavilla",
        "not available in the selected",
        "not available in the uploaded",
        "not found in the selected",
        "not found in the uploaded",
        "\u0b95\u0bbf\u0b9f\u0bc8\u0b95\u0bcd\u0b95\u0bb5\u0bbf\u0bb2\u0bcd\u0bb2\u0bc8",
        "does not contain information",
        "no information about",
        "is not mentioned in",
        "is not discussed in",
        "context does not",
    ]

    return any(indicator in answer_lower for indicator in fallback_indicators)


def fallback_for_subquery(sub_query: str, language: str, document_mode: str = "single") -> str:
    topic = sub_query.strip().rstrip("?.!")

    if document_mode == "multiple":
        scope = "selected PDFs"
    elif document_mode == "all":
        scope = "uploaded documents"
    else:
        scope = "selected document"

    return f"Information about '{topic}' is not available in the {scope}."




def query_rag(
    user_query: str,
    language: str = "english",
    session_id: str = "default_session",
    user_id: str = "default_user",
    document_id: str = None,
    document_mode: str = "single",
    document_ids=None,
    tenant_id: str = LOCAL_TENANT
):
    try:
        selected_language = normalize_language(language)
        selected_mode = normalize_document_mode(document_mode)
        cleaned_document_ids = clean_document_ids(document_ids)

        print("\n\U0001f9e0 [KRISH AI RAG]")
        print(f"Selected language inside rag.py: {selected_language}")
        print(f"User query: {user_query}")
        print(f"Document Mode: {selected_mode}")
        print(f"Document ID: {document_id}")
        print(f"Document IDs: {cleaned_document_ids}")

        retriever_filter = build_retriever_filter(
            user_id=user_id,
            document_id=document_id,
            document_mode=selected_mode,
            document_ids=cleaned_document_ids,
            tenant_id=tenant_id
        )

        print(f"\U0001f512 Retriever Filter: {retriever_filter}")

        # Search wider so a long PDF (100+ pages) still surfaces the right page;
        # the keyword filter and grounding check below remove what doesn't fit.
        search_k = 40 if selected_mode in ["all", "multiple"] else 25

        selected_document_label = get_selected_document_label(
            user_id=user_id,
            document_id=document_id,
            document_mode=selected_mode,
            document_ids=cleaned_document_ids
        )

        # A follow-up ("fully explain to me") borrows the previous question's
        # topic, so the chat can be held in sentences instead of repeating
        # the subject every time.
        previous_turn = get_previous_turn(session_id, user_id)
        resolved_user_query = resolve_followup_question(user_query, previous_turn)

        if resolved_user_query != user_query:
            # A resolved follow-up is one question made of two parts; splitting
            # it again on "what is" / "and" tears it into fragments.
            sub_queries = [resolved_user_query]
        else:
            sub_queries = split_mixed_query(resolved_user_query)
        print(f"\n🧩 Split sub-queries: {sub_queries}")

        answer_parts = []
        sources = []
        source_labels = []
        seen_sources = set()
        any_answered = False
        retrieval_queries_used = []

        greeting_answer = get_greeting_answer(user_query, selected_language)
        if greeting_answer:
            return {
                "answer": greeting_answer,
                "sources": [],
                "source_labels": []
            }

        # Guard: reject very short/meaningless queries
        clean_query = re.sub(r"\s+", "", user_query or "")
        if len(clean_query) < 3:
            empty_answer = "Please ask a proper question."

            return {
                "answer": empty_answer,
                "sources": [],
                "source_labels": []
            }

        all_chunks = fetch_all_chunks(retriever_filter)
        document_vocabulary = get_vocabulary_from_chunks(all_chunks)
        print(f"📚 Document chunks available: {len(all_chunks)}")

        for sub_q in sub_queries:
            sub_q = correct_spelling_with_vocabulary(sub_q, document_vocabulary)
            rag_sub_q = rewrite_subquery_for_rag(sub_q, selected_language)

            raw_docs, retrieval_query = retrieve_for_subquery(
                sub_query=rag_sub_q,
                retriever_filter=retriever_filter,
                search_k=search_k,
                selected_language=selected_language
            )

            extra_docs, _ = retrieve_for_subquery(
                sub_query=sub_q,
                retriever_filter=retriever_filter,
                search_k=search_k,
                selected_language=selected_language
            )

            # Hybrid search: vector results plus a direct keyword search, so the
            # page that literally names the topic is never missed.
            keyword_docs = keyword_search_chunks(all_chunks, rag_sub_q)

            seen_chunk_keys = set()
            vector_docs = []

            for doc in (raw_docs + extra_docs):
                meta = doc.metadata or {}
                chunk_key = f"{meta.get('document_id')}-{meta.get('chunk_index')}"

                if chunk_key not in seen_chunk_keys:
                    seen_chunk_keys.add(chunk_key)
                    vector_docs.append(doc)

            raw_docs = fuse_search_results(vector_docs, keyword_docs)
            retrieval_queries_used.append(retrieval_query)

            print(f"\n📦 Sub-query: '{sub_q}'")
            print(f"🧠 Rewritten question: {rag_sub_q}")
            print(f"🔎 Retrieval query: {retrieval_query}")

            filtered_docs = hard_filter_retrieved_docs(
                docs=raw_docs,
                user_id=user_id,
                document_id=document_id,
                document_mode=selected_mode,
                document_ids=cleaned_document_ids,
                tenant_id=tenant_id
            )

            if not filtered_docs:
                answer_parts.append(
                    fallback_for_subquery(sub_q, selected_language, selected_mode)
                )
                continue

            # With a reranker, keep a wider candidate set for it to judge.
            candidate_limit = 15 if get_reranker() is not None else 6
            relevant_docs = filter_relevant_docs_for_question(
                rag_sub_q, filtered_docs, limit=candidate_limit
            )

            print(f"🔍 Keyword relevant docs: {len(relevant_docs)}")

            if not relevant_docs:
                answer_parts.append(
                    fallback_for_subquery(sub_q, selected_language, selected_mode)
                )
                continue

            answer_docs = rerank_documents(rag_sub_q, relevant_docs, limit=4)

            if is_document_level_question(rag_sub_q):
                # "What is this document about" - show the model the whole
                # document, evenly sampled, not just keyword hits.
                context_docs = sample_across_document(all_chunks, max_docs=8)
                answer_docs = context_docs[:4]
            else:
                # The model reads the hits plus their neighbouring chunks, so a
                # definition split across a chunk boundary is still available.
                context_docs = expand_with_neighbour_chunks(answer_docs, all_chunks, max_docs=8)
            sub_context_text = docs_to_context_text(context_docs)

            print(f"📄 Context chunks: {[d.metadata.get('chunk_index') for d in context_docs]}")
            fallback_line = fallback_for_subquery(sub_q, selected_language, selected_mode)

            raw_answer = generate_answer_from_context(
                sub_query=rag_sub_q,
                context_text=sub_context_text,
                language=selected_language,
                original_user_query=sub_q,
                fallback_line=fallback_line
            )

            if not raw_answer or raw_answer == fallback_line:
                answer_parts.append(fallback_line)
                continue

            answer_parts.append(raw_answer)
            any_answered = True

            for doc in select_source_docs(raw_answer, context_docs):
                file_name = doc.metadata.get("file_name", "Unknown")
                page_number = doc.metadata.get("page_number", "Unknown")
                chunk_index = doc.metadata.get("chunk_index", "Unknown")
                source_document_id = doc.metadata.get("document_id", "Unknown")

                source_key = f"{source_document_id}-{file_name}-{page_number}-{chunk_index}"

                if source_key not in seen_sources:
                    sources.append({
                        "document_id": source_document_id,
                        "file_name": file_name,
                        "page_number": page_number,
                        "chunk_index": chunk_index
                    })
                    source_labels.append(
                        f"{file_name} - Page {page_number} - Chunk {chunk_index}"
                    )
                    seen_sources.add(source_key)

        if not answer_parts:
            answer = get_empty_answer(selected_language, selected_mode)
            sources = []
            source_labels = []
        elif len(answer_parts) == 1:
            answer = answer_parts[0]
        else:
            # Each part may already open with "Seri,"/"\u0b9a\u0bb0\u0bbf," - drop it so the
            # joined answer doesn't read "Seri, Seri, ...".
            answer_parts = [
                re.sub(r"^\s*(seri|\u0b9a\u0bb0\u0bbf)\s*,\s*", "", part, flags=re.IGNORECASE)
                for part in answer_parts
            ]

            answer = "\n\n".join(answer_parts)

        if not any_answered:
            sources = []
            source_labels = []

        retrieval_query = " | ".join(retrieval_queries_used)

        stored_document_id = document_id if selected_mode == "single" else None

        if selected_mode == "single":
            stored_document_ids = [document_id] if document_id else []
        elif selected_mode == "multiple":
            stored_document_ids = cleaned_document_ids
        else:
            stored_document_ids = []

        if chat_sessions_collection is not None:
            chat_sessions_collection.insert_one({
                "session_id": session_id,
                "user_id": user_id,
                "tenant_id": tenant_id or LOCAL_TENANT,
                "document_id": stored_document_id,
                "document_ids": stored_document_ids,
                "document_mode": selected_mode,
                "document_name": selected_document_label,
                "query": user_query,
                "resolved_query": resolved_user_query,
                "retrieval_query": retrieval_query,
                "answer": answer,
                "language": selected_language,
                "sources": sources,
                "source_labels": source_labels,
                "model_used": MAIN_LLM_MODEL,
                "embedding_model": EMBEDDING_MODEL,
                "timestamp": datetime.utcnow()
            })

        return {
            "answer": answer,
            "sources": sources,
            "source_labels": source_labels
        }

    except Exception as e:
        print("\n\u274c CRITICAL ERROR IN RAG QUERY ENGINE \u274c")
        import traceback
        traceback.print_exc()
        raise e


def delete_document_by_id(
    document_id: str,
    user_id: str = "default_user",
    tenant_id: str = LOCAL_TENANT
):
    """
    Delete one uploaded document fully:
    1. Delete from ChromaDB vector store
    2. Delete from MongoDB documents collection
    3. Delete from MongoDB chunks collection
    4. Delete from MongoDB vectors collection
    5. Keep chat history, but selected document will no longer be available
    """
    try:
        if not document_id:
            return {
                "status": "error",
                "message": "document_id is required.",
                "deleted_chroma_count": 0,
                "deleted_document_count": 0,
                "deleted_chunks_count": 0,
                "deleted_vectors_count": 0
            }

        print("\n🗑️ [KRISH AI] Deleting document")
        print(f"Document ID: {document_id}")
        print(f"User ID: {user_id}")

        document_record = None

        if document_collection is not None:
            document_record = document_collection.find_one({
                "document_id": document_id,
                "user_id": user_id,
                "tenant_id": tenant_id or LOCAL_TENANT
            })

        if not document_record:
            return {
                "status": "not_found",
                "message": "Document not found.",
                "deleted_chroma_count": 0,
                "deleted_document_count": 0,
                "deleted_chunks_count": 0,
                "deleted_vectors_count": 0
            }

        # Delete ChromaDB chunks
        deleted_chroma_count = 0

        try:
            chroma_records = vector_store.get(
                where={
                    "$and": [
                        {"document_id": document_id},
                        {"user_id": user_id}
                    ]
                }
            )

            chroma_ids = chroma_records.get("ids", [])

            if chroma_ids:
                vector_store.delete(ids=chroma_ids)
                deleted_chroma_count = len(chroma_ids)

            print(f"✅ Deleted {deleted_chroma_count} chunks from ChromaDB.")

        except Exception as chroma_error:
            print("⚠️ ChromaDB delete failed.")
            print(chroma_error)

        # Delete MongoDB records
        deleted_document_count = 0
        deleted_chunks_count = 0
        deleted_vectors_count = 0

        if document_collection is not None:
            result = document_collection.delete_many({
                "document_id": document_id,
                "user_id": user_id
            })
            deleted_document_count = result.deleted_count

        if chunks_collection is not None:
            result = chunks_collection.delete_many({
                "document_id": document_id,
                "user_id": user_id
            })
            deleted_chunks_count = result.deleted_count

        if vectors_collection is not None:
            result = vectors_collection.delete_many({
                "document_id": document_id,
                "user_id": user_id
            })
            deleted_vectors_count = result.deleted_count

        print(f"✅ Deleted documents: {deleted_document_count}")
        print(f"✅ Deleted chunks: {deleted_chunks_count}")
        print(f"✅ Deleted vectors: {deleted_vectors_count}")

        return {
            "status": "success",
            "message": "Document deleted successfully.",
            "document_id": document_id,
            "file_name": document_record.get("file_name"),
            "deleted_chroma_count": deleted_chroma_count,
            "deleted_document_count": deleted_document_count,
            "deleted_chunks_count": deleted_chunks_count,
            "deleted_vectors_count": deleted_vectors_count
        }

    except Exception as e:
        print("\n❌ CRITICAL ERROR WHILE DELETING DOCUMENT ❌")
        import traceback
        traceback.print_exc()
        raise e

def backfill_tenant_metadata():
    """
    Give pre-multi-tenancy chunks a tenant.

    Chunks indexed before API keys existed carry no tenant_id, and the strict
    retrieval filter cannot match a field that is not there - the local React
    app would suddenly find nothing. They belong to the local tenant, so that
    is what they get, once.
    """
    try:
        records = vector_store.get(include=["metadatas"])
    except Exception as e:
        print(f"⚠️ Tenant backfill skipped: {e}")
        return 0

    ids = records.get("ids") or []
    metadatas = records.get("metadatas") or []

    stale_ids = []
    stale_metadatas = []

    for index, metadata in enumerate(metadatas):
        if metadata and not metadata.get("tenant_id") and index < len(ids):
            updated = dict(metadata)
            updated["tenant_id"] = LOCAL_TENANT
            stale_ids.append(ids[index])
            stale_metadatas.append(updated)

    if not stale_ids:
        return 0

    try:
        vector_store._collection.update(ids=stale_ids, metadatas=stale_metadatas)
        print(f"🏷️  Tagged {len(stale_ids)} existing chunks as tenant '{LOCAL_TENANT}'")
    except Exception as e:
        print(f"⚠️ Tenant backfill failed: {e}")
        return 0

    for collection in (document_collection, chunks_collection, vectors_collection):
        if collection is None:
            continue
        try:
            collection.update_many(
                {"tenant_id": {"$exists": False}},
                {"$set": {"tenant_id": LOCAL_TENANT}}
            )
        except Exception as e:
            print(f"⚠️ Mongo tenant backfill failed: {e}")

    return len(stale_ids)


backfill_tenant_metadata()


# Load the reranker in the background at startup: loading it costs ~20 seconds,
# which should not land on the user's first question.
if RERANKER_ENABLED:
    import threading

    threading.Thread(target=get_reranker, daemon=True).start()
