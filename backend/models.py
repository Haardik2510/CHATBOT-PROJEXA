"""Pydantic models for the Academic Chatbot"""
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Literal
from datetime import datetime, timezone
import uuid


# User Models
class UserBase(BaseModel):
    email: EmailStr
    name: str
    role: Literal["student", "faculty", "admin"] = "student"


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class User(UserBase):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# Document Models
class DocumentBase(BaseModel):
    title: str
    description: Optional[str] = None
    doc_type: Literal["pdf", "docx", "txt", "csv", "pptx", "url"] = "pdf"


class Document(DocumentBase):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    file_size: int = 0
    chunk_count: int = 0
    status: Literal["pending", "processing", "indexed", "failed"] = "pending"
    uploaded_by: Optional[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    indexed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class DocumentResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    doc_type: str
    filename: str
    file_size: int
    chunk_count: int
    status: str
    uploaded_by: Optional[str]
    created_at: str
    indexed_at: Optional[str]
    error_message: Optional[str] = None


class DocumentChunkPreview(BaseModel):
    chunk_index: int
    chunk_text: str
    relevance_score: Optional[float] = None
    metadata: dict = {}


class DocumentChunkPreviewResponse(BaseModel):
    document_id: str
    title: str
    status: str
    chunk_count: int
    chunks: List[DocumentChunkPreview] = []


class DocumentBulkDeleteRequest(BaseModel):
    document_ids: List[str] = Field(default_factory=list, min_length=1)


class DocumentBulkDeleteResponse(BaseModel):
    deleted_count: int
    not_found_ids: List[str] = []


# Chat Models
class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    voice_input: bool = False
    answer_mode: Literal["database", "internet"] = "database"


class SourceCitation(BaseModel):
    document_id: str
    document_title: str
    chunk_text: str
    relevance_score: float


class ChatResponse(BaseModel):
    response: str
    sources: List[SourceCitation] = []
    session_id: str
    voice_output: bool = False
    answer_mode: Literal["database", "internet"] = "database"


class RetrievalEvaluationRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=10)


class RetrievalEvaluationResponse(BaseModel):
    query: str
    vector_backend: str
    embedding_provider: str
    embedding_model: str
    chunk_count: int
    results: List[DocumentChunkPreview] = []


class ChatSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    messages: List[dict] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Analytics Models
class QueryLog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    query: str
    response_length: int
    sources_count: int
    voice_input: bool
    processing_time_ms: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalyticsOverview(BaseModel):
    total_queries: int
    total_documents: int
    total_users: int
    queries_today: int
    avg_response_time_ms: float
    voice_query_percentage: float


class DailyStats(BaseModel):
    date: str
    query_count: int
    unique_users: int
    avg_response_time: float


# URL Scraping
class URLScrapeRequest(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
