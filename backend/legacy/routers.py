import os
import re
import shutil
import uuid
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional

from .rag import process_and_store_document, query_rag, delete_document_by_id
from .database import (
    chat_sessions_collection,
    document_collection,
    chunks_collection,
    vectors_collection,
)

router = APIRouter()

AUDIO_DIR = os.path.join("app", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)


class ChatRequest(BaseModel):
    query: str
    language: str = "tanglish"
    user_id: str = "default_user"
    session_id: str = "default_session"

    # Old single document support
    document_id: Optional[str] = None

    # New multi-document support
    document_mode: str = "single"   # single | multiple | all
    document_ids: List[str] = []


class ChatResponse(BaseModel):
    answer: str
    sources: List[dict] = []
    source_labels: List[str] = []


class DocumentUploadResponse(BaseModel):
    filename: str
    message: str
    document_id: Optional[str] = None


class RenameDocumentRequest(BaseModel):
    new_file_name: str
    user_id: str = "default_user"


class TTSRequest(BaseModel):
    text: str
    language: str = "tanglish"
    voice: Optional[str] = None


def normalize_language(language: str) -> str:
    """Answers and speech are English only (see rag.normalize_language)."""
    return "english"


def normalize_document_mode(mode: str) -> str:
    selected_mode = (mode or "single").lower().strip()

    if selected_mode == "all":
        return "all"

    if selected_mode == "multiple":
        return "multiple"

    return "single"


def normalize_pdf_name(file_name: str) -> str:
    cleaned = (file_name or "").strip()

    cleaned = cleaned.replace("/", "-")
    cleaned = cleaned.replace("\\", "-")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        raise HTTPException(status_code=400, detail="Document name cannot be empty.")

    if len(cleaned) > 160:
        raise HTTPException(status_code=400, detail="Document name is too long.")

    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"

    return cleaned


def clean_text_for_tts(text: str) -> str:
    if not text:
        return ""

    cleaned = text
    cleaned = cleaned.replace("*", "")
    cleaned = cleaned.replace("#", "")
    cleaned = cleaned.replace("`", "")
    cleaned = cleaned.replace("•", "")
    cleaned = cleaned.replace("-", " ")
    cleaned = cleaned.replace("\n", ". ")
    cleaned = cleaned.replace(":", ". ")
    cleaned = cleaned.replace(";", ". ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    max_chars = 2500
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "."

    return cleaned


def get_voice_for_language(language: str, voice: Optional[str] = None) -> str:
    if voice:
        return voice

    lang = normalize_language(language)

    if lang == "tamil":
        return "ta-IN-PallaviNeural"

    return "en-US-JennyNeural"


def get_rate_for_language(language: str) -> str:
    lang = normalize_language(language)

    if lang == "tamil":
        return "-12%"

    if lang == "tanglish":
        return "-10%"

    return "-8%"


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Form("default_user")
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    temp_file_path = f"temp_{file.filename}"

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")

    try:
        result = process_and_store_document(temp_file_path, user_id)
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {e}")

    if os.path.exists(temp_file_path):
        os.remove(temp_file_path)

    if result.get("status") == "duplicate":
        raise HTTPException(
            status_code=409,
            detail="This document is already uploaded in your database."
        )

    if result.get("status") == "no_text":
        raise HTTPException(
            status_code=422,
            detail=result.get("message", "No readable text found in this PDF.")
        )

    if result.get("status") == "no_chunks":
        raise HTTPException(
            status_code=422,
            detail=result.get("message", "No chunks were created from this PDF.")
        )

    return DocumentUploadResponse(
        filename=file.filename,
        message=f"Successfully processed {result.get('chunks')} chunks into Vector DB.",
        document_id=result.get("document_id")
    )


@router.get("/documents")
async def get_uploaded_documents(user_id: str = Query("default_user")):
    if document_collection is None:
        return {"documents": []}

    records = list(
        document_collection
        .find({"user_id": user_id})
        .sort("uploaded_at", -1)
    )

    documents = []

    for record in records:
        documents.append({
            "document_id": record.get("document_id"),
            "file_name": record.get("file_name", "Unknown PDF"),
            "pages": record.get("pages", 0),
            "total_chunks": record.get("total_chunks", 0),
            "uploaded_at": str(record.get("uploaded_at", "")),
        })

    return {"documents": documents}


@router.patch("/documents/{document_id}/rename")
async def rename_uploaded_document(
    document_id: str,
    request: RenameDocumentRequest
):
    if document_collection is None:
        raise HTTPException(status_code=500, detail="MongoDB is not connected.")

    user_id = request.user_id or "default_user"
    new_file_name = normalize_pdf_name(request.new_file_name)

    existing_doc = document_collection.find_one({
        "document_id": document_id,
        "user_id": user_id
    })

    if not existing_doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    duplicate_doc = document_collection.find_one({
        "user_id": user_id,
        "file_name": new_file_name,
        "document_id": {"$ne": document_id}
    })

    if duplicate_doc:
        raise HTTPException(
            status_code=409,
            detail="Another document already has this name."
        )

    old_file_name = existing_doc.get("file_name", "")

    document_result = document_collection.update_one(
        {
            "document_id": document_id,
            "user_id": user_id
        },
        {
            "$set": {
                "file_name": new_file_name,
                "renamed_at": datetime.utcnow()
            }
        }
    )

    chunks_updated = 0
    vectors_updated = 0
    chats_updated = 0

    if chunks_collection is not None:
        result = chunks_collection.update_many(
            {
                "document_id": document_id,
                "user_id": user_id
            },
            {
                "$set": {
                    "file_name": new_file_name,
                    "renamed_at": datetime.utcnow()
                }
            }
        )
        chunks_updated = result.modified_count

    if vectors_collection is not None:
        result = vectors_collection.update_many(
            {
                "document_id": document_id,
                "user_id": user_id
            },
            {
                "$set": {
                    "file_name": new_file_name,
                    "renamed_at": datetime.utcnow()
                }
            }
        )
        vectors_updated = result.modified_count

    if chat_sessions_collection is not None:
        result = chat_sessions_collection.update_many(
            {
                "document_id": document_id,
                "user_id": user_id
            },
            {
                "$set": {
                    "document_name": new_file_name
                }
            }
        )
        chats_updated = result.modified_count

    return {
        "status": "success",
        "message": "Document renamed successfully.",
        "document_id": document_id,
        "old_file_name": old_file_name,
        "file_name": new_file_name,
        "document_updated": document_result.modified_count,
        "chunks_updated": chunks_updated,
        "vectors_updated": vectors_updated,
        "chats_updated": chats_updated
    }


@router.delete("/documents/{document_id}")
async def delete_uploaded_document(
    document_id: str,
    user_id: str = Query("default_user")
):
    try:
        result = delete_document_by_id(
            document_id=document_id,
            user_id=user_id
        )

        if result.get("status") == "not_found":
            raise HTTPException(
                status_code=404,
                detail="Document not found."
            )

        if result.get("status") == "error":
            raise HTTPException(
                status_code=400,
                detail=result.get("message", "Document delete failed.")
            )

        return result

    except HTTPException:
        raise

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting document: {e}"
        )


@router.post("/chat", response_model=ChatResponse)
async def chat_with_document(request: ChatRequest):
    try:
        selected_language = normalize_language(request.language)
        selected_document_mode = normalize_document_mode(request.document_mode)

        clean_document_ids = [
            doc_id for doc_id in (request.document_ids or [])
            if doc_id
        ]

        if selected_document_mode == "single" and not request.document_id:
            raise HTTPException(
                status_code=400,
                detail="document_id is required for single document mode."
            )

        if selected_document_mode == "multiple" and not clean_document_ids:
            raise HTTPException(
                status_code=400,
                detail="document_ids are required for multiple document mode."
            )

        print("\n📩 [KRISH AI CHAT REQUEST]")
        print(f"Query: {request.query}")
        print(f"Language received from frontend: {request.language}")
        print(f"Normalized language: {selected_language}")
        print(f"Session ID: {request.session_id}")
        print(f"User ID: {request.user_id}")
        print(f"Document Mode: {selected_document_mode}")
        print(f"Document ID: {request.document_id}")
        print(f"Document IDs: {clean_document_ids}")

        response_data = query_rag(
            user_query=request.query,
            language=selected_language,
            session_id=request.session_id,
            user_id=request.user_id,
            document_id=request.document_id,
            document_mode=selected_document_mode,
            document_ids=clean_document_ids
        )

        return ChatResponse(
            answer=response_data.get("answer", ""),
            sources=response_data.get("sources", []),
            source_labels=response_data.get("source_labels", [])
        )

    except HTTPException:
        raise

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during RAG query: {e}")


@router.post("/tts")
async def generate_tts(request: TTSRequest):
    try:
        import edge_tts
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="edge-tts is not installed. Run: ./venv/bin/pip install edge-tts"
        )

    selected_language = normalize_language(request.language)
    cleaned_text = clean_text_for_tts(request.text)

    if not cleaned_text:
        raise HTTPException(status_code=400, detail="Text is empty.")

    voice = get_voice_for_language(selected_language, request.voice)
    rate = get_rate_for_language(selected_language)

    audio_filename = f"tts_{uuid.uuid4().hex}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)

    print("\n🔊 [KRISH AI TTS REQUEST]")
    print(f"Original Language: {request.language}")
    print(f"Normalized Language: {selected_language}")
    print(f"Voice: {voice}")
    print(f"Rate: {rate}")
    print(f"Text length: {len(cleaned_text)}")
    print(f"Audio path: {audio_path}")

    try:
        communicate = edge_tts.Communicate(
            text=cleaned_text,
            voice=voice,
            rate=rate
        )

        await communicate.save(audio_path)

        if not os.path.exists(audio_path):
            raise HTTPException(
                status_code=500,
                detail="Audio file was not created."
            )

        audio_size = os.path.getsize(audio_path)

        print(f"✅ Audio created successfully: {audio_filename}")
        print(f"📦 Audio size: {audio_size} bytes")

        if audio_size == 0:
            raise HTTPException(
                status_code=500,
                detail="Audio file is empty."
            )

        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            filename=audio_filename
        )

    except HTTPException:
        raise

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Edge TTS failed: {e}")


@router.get("/chat-sessions")
async def get_chat_sessions(user_id: str = Query("default_user")):
    if chat_sessions_collection is None:
        return {"sessions": []}

    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$sort": {"timestamp": -1}},
        {
            "$group": {
                "_id": "$session_id",
                "session_id": {"$first": "$session_id"},
                "title": {"$first": "$query"},
                "last_message": {"$first": "$answer"},
                "updated_at": {"$first": "$timestamp"},
                "message_count": {"$sum": 1},
                "document_id": {"$first": "$document_id"},
                "document_name": {"$first": "$document_name"},
                "language": {"$first": "$language"},
                "document_mode": {"$first": "$document_mode"},
                "document_ids": {"$first": "$document_ids"},
            }
        },
        {"$sort": {"updated_at": -1}},
        {"$limit": 50}
    ]

    sessions = list(chat_sessions_collection.aggregate(pipeline))

    cleaned_sessions = []

    for session in sessions:
        cleaned_sessions.append({
            "session_id": session.get("session_id"),
            "title": session.get("title", "Untitled Chat"),
            "last_message": session.get("last_message", ""),
            "updated_at": str(session.get("updated_at", "")),
            "message_count": session.get("message_count", 0),
            "document_id": session.get("document_id"),
            "document_name": session.get("document_name"),
            "language": session.get("language"),
            "document_mode": session.get("document_mode"),
            "document_ids": session.get("document_ids", []),
        })

    return {"sessions": cleaned_sessions}


@router.get("/chat-history/{session_id}")
async def get_chat_history(
    session_id: str,
    user_id: str = Query("default_user")
):
    if chat_sessions_collection is None:
        return {"messages": []}

    records = list(
        chat_sessions_collection
        .find({"session_id": session_id, "user_id": user_id})
        .sort("timestamp", 1)
    )

    messages = []

    for record in records:
        messages.append({
            "role": "user",
            "content": record.get("query", ""),
            "sources": [],
            "source_labels": [],
            "language": record.get("language", "tanglish"),
        })

        messages.append({
            "role": "bot",
            "content": record.get("answer", ""),
            "sources": record.get("sources", []),
            "source_labels": record.get("source_labels", []),
            "language": record.get("language", "tanglish"),
        })

    return {"messages": messages}


@router.delete("/chat-sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    user_id: str = Query("default_user")
):
    if chat_sessions_collection is None:
        raise HTTPException(status_code=500, detail="MongoDB is not connected.")

    result = chat_sessions_collection.delete_many({
        "session_id": session_id,
        "user_id": user_id
    })

    return {
        "status": "success",
        "message": "Conversation deleted successfully.",
        "session_id": session_id,
        "deleted_count": result.deleted_count
    }