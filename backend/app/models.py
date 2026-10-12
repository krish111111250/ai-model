from pydantic import BaseModel
from typing import List, Optional

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    answer: str
    sources: Optional[List[str]] = []

class DocumentUploadResponse(BaseModel):
    filename: str
    message: str