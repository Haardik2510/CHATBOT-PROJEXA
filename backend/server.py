"""Main FastAPI application for SET Academic Chatbot"""
import json
import base64
import textwrap
import re
import gc
import shutil
from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import httpx
import os
import logging
import tempfile
import fitz
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
import time
import uuid

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from models import (
    UserCreate, UserLogin, UserResponse, TokenResponse, User,
    Document, DocumentResponse, ChatRequest, ChatResponse, SourceCitation, ChatImage,
    ChatArtifact, PdfExportRequest, PdfExportResponse,
    ChatSession, QueryLog, AnalyticsOverview, DailyStats, URLScrapeRequest,
    DocumentChunkPreview, DocumentChunkPreviewResponse,
    RetrievalEvaluationRequest, RetrievalEvaluationResponse,
    DocumentBulkDeleteRequest, DocumentBulkDeleteResponse,
)
from auth import (
    hash_password, verify_password, create_access_token, 
    decode_token, require_role, verify_clerk_session_token, fetch_clerk_user
)
from document_processor import DocumentProcessor
from rag_engine import rag_engine, OLLAMA_CHAT_MODEL
from large_pdf_rag import (
    answer_question_payload as answer_large_pdf_question,
    chunk_document as chunk_large_pdf_document,
    collection_has_data as large_pdf_collection_has_data,
    delete_document as delete_large_pdf_document,
    embed_and_store as embed_large_pdf_chunks,
    extract_and_clean_pdf as extract_large_pdf_pages,
    index_pdf_document,
    job_collection_name as large_pdf_job_collection_name,
    preview_document_chunks as preview_large_pdf_chunks,
)
from web_search import WebSearchFallback, get_web_search_fallback
from events_feed import KRMUEventsFeed
from app_store import AppStore, utc_now_iso
from supabase_client import (
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
    SUPABASE_STORAGE_BUCKET,
    fetch_supabase_user,
    get_supabase_admin_client,
    get_supabase_public_client,
    has_supabase_config,
    download_bytes,
    upload_bytes,
)

ENABLE_WEB_FALLBACK = os.environ.get("ENABLE_WEB_FALLBACK", "false").strip().lower() == "true"
LARGE_PDF_COLLECTION_NAME = os.environ.get("LARGE_PDF_COLLECTION_NAME", "render-large-pdf-documents").strip() or "render-large-pdf-documents"

# MongoDB connection
mongo_url = os.environ.get("MONGO_URL")
db_name = os.environ.get("DB_NAME")
client = AsyncIOMotorClient(mongo_url) if mongo_url else None
db = client[db_name] if client and db_name else None
store = AppStore(db)

# Create the main app
app = FastAPI(
    title="SET Academic Chatbot API",
    description="Multimodal academic chatbot for K.R. Mangalam University",
    version="1.0.0"
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")
security = HTTPBearer(auto_error=False)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PDF_EXPORT_PATTERN = re.compile(
    r"\b(convert|export|save|turn|make|create|download)\b.*\b(this|last|latest|previous|above|response|answer|message|summary|event)\b.*\bpdf\b|"
    r"\bpdf\b.*\b(this|last|latest|previous|above|response|answer|message|summary|event)\b",
    re.IGNORECASE,
)

DOCUMENT_PROCESS_BASE_TIMEOUT_SECONDS = max(300, int(os.environ.get("DOCUMENT_PROCESS_BASE_TIMEOUT_SECONDS", "300")))
DOCUMENT_PROCESS_MAX_TIMEOUT_SECONDS = max(
    DOCUMENT_PROCESS_BASE_TIMEOUT_SECONDS,
    int(os.environ.get("DOCUMENT_PROCESS_MAX_TIMEOUT_SECONDS", "5400")),
)
DOCUMENT_INDEX_BASE_TIMEOUT_SECONDS = max(300, int(os.environ.get("DOCUMENT_INDEX_BASE_TIMEOUT_SECONDS", "300")))
DOCUMENT_INDEX_MAX_TIMEOUT_SECONDS = max(
    DOCUMENT_INDEX_BASE_TIMEOUT_SECONDS,
    int(os.environ.get("DOCUMENT_INDEX_MAX_TIMEOUT_SECONDS", "5400")),
)
SUPABASE_SPLIT_THRESHOLD_BYTES = int(os.environ.get("SUPABASE_SPLIT_THRESHOLD_BYTES", str(45 * 1024 * 1024)))
SUPABASE_MAX_PART_BYTES = int(os.environ.get("SUPABASE_MAX_PART_BYTES", str(40 * 1024 * 1024)))
SSE_PAGE_BATCH_SIZE = max(1, int(os.environ.get("SSE_PAGE_BATCH_SIZE", "5")))


def _parse_cors_origins(raw_value: str) -> List[str]:
    """Parse comma-separated CORS origins while ignoring blanks."""
    return [origin.strip().rstrip("/") for origin in (raw_value or "").split(",") if origin.strip()]


def _resolve_cors_origin_regex(explicit_origins: List[str]) -> Optional[str]:
    """
    Allow stable localhost origins and Vercel-hosted frontends without needing
    an exact env update for every new preview/custom deployment.
    """
    configured_regex = os.environ.get("CORS_ORIGIN_REGEX", "").strip()
    if configured_regex:
        return configured_regex

    if any(origin.endswith(".vercel.app") for origin in explicit_origins):
        return r"^https://([a-zA-Z0-9-]+\.)*vercel\.app$"

    return None


def _document_process_timeout_seconds(file_type: str, file_size: int) -> Optional[int]:
    """Scale extraction timeout with file size, especially for large PDFs."""
    if _should_disable_global_document_timeout(file_type, file_size):
        return None
    size_mb = max(file_size / (1024 * 1024), 0.0)
    per_mb = 28 if file_type == "pdf" else 8
    timeout = int(DOCUMENT_PROCESS_BASE_TIMEOUT_SECONDS + (size_mb * per_mb))
    return min(max(timeout, DOCUMENT_PROCESS_BASE_TIMEOUT_SECONDS), DOCUMENT_PROCESS_MAX_TIMEOUT_SECONDS)


def _document_index_timeout_seconds(chunk_count: int, file_size: int) -> Optional[int]:
    """Scale indexing timeout based on chunk count and document size."""
    if _should_disable_global_document_timeout("pdf", file_size):
        return None
    size_mb = max(file_size / (1024 * 1024), 0.0)
    timeout = int(
        DOCUMENT_INDEX_BASE_TIMEOUT_SECONDS
        + min(chunk_count, 1200) * 1.6
        + size_mb * 12
    )
    return min(max(timeout, DOCUMENT_INDEX_BASE_TIMEOUT_SECONDS), DOCUMENT_INDEX_MAX_TIMEOUT_SECONDS)


def _should_disable_global_document_timeout(file_type: str, file_size: int) -> bool:
    """Allow large PDFs to finish in the background instead of hitting an app-level timeout."""
    size_mb = max(file_size / (1024 * 1024), 0.0)
    return file_type == "pdf" and size_mb >= 8

# ==================== Helper Functions ====================

async def get_current_user_from_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    """Get the current authenticated user from JWT token"""
    if not credentials:
        return None
    
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        return None
    
    return {
        "id": payload.get("sub"),
        "email": payload.get("email"),
        "name": payload.get("name"),
        "role": payload.get("role", "student")
    }


def _format_current_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user.get("role", "student"),
        "picture": user.get("picture"),
    }


def _extract_primary_email(clerk_user: dict) -> str:
    """Return the primary email address from a Clerk user payload."""
    primary_email_id = clerk_user.get("primary_email_address_id")
    for address in clerk_user.get("email_addresses", []):
        if address.get("id") == primary_email_id:
            return address.get("email_address")

    email_addresses = clerk_user.get("email_addresses", [])
    return email_addresses[0].get("email_address") if email_addresses else ""


def _extract_supabase_name(supabase_user: dict) -> str:
    metadata = supabase_user.get("user_metadata") or {}
    app_metadata = supabase_user.get("app_metadata") or {}
    return (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("user_name")
        or app_metadata.get("name")
        or supabase_user.get("email", "").split("@")[0]
        or "User"
    )


def _extract_supabase_picture(supabase_user: dict) -> Optional[str]:
    metadata = supabase_user.get("user_metadata") or {}
    return metadata.get("avatar_url") or metadata.get("picture")


async def sync_supabase_user(supabase_user: dict) -> Optional[dict]:
    """Upsert a Supabase-authenticated user into the application profile store."""
    user_id = supabase_user.get("id")
    email = supabase_user.get("email")
    if not user_id or not email:
        return None

    existing_user = await store.get_user_by_id(user_id)
    user_role = (
        existing_user.get("role")
        if existing_user
        else (supabase_user.get("user_metadata") or {}).get("role", "student")
    )
    if user_role not in {"student", "faculty", "admin"}:
        user_role = "student"

    record = {
        "id": user_id,
        "email": email,
        "name": _extract_supabase_name(supabase_user),
        "role": user_role,
        "picture": _extract_supabase_picture(supabase_user),
        "auth_provider": "supabase",
        "is_active": True,
        "updated_at": utc_now_iso(),
    }

    if existing_user and existing_user.get("created_at"):
        record["created_at"] = existing_user["created_at"]

    return await store.save_user(record)


async def upsert_clerk_user_profile(
    clerk_user_id: str,
    email: str,
    name: str,
    picture: Optional[str] = None,
    requested_role: Optional[str] = None,
) -> Optional[dict]:
    """Upsert a Clerk user using profile data already available to the app."""
    if not clerk_user_id or not email:
        return None

    existing_user = await store.get_user_by_clerk_user_id(clerk_user_id)
    if existing_user:
        existing_user.update(
            {"email": email, "name": name, "picture": picture, "auth_provider": "clerk"}
        )
        return await store.save_user(existing_user)

    existing_by_email = await store.get_user_by_email(email)
    if existing_by_email:
        existing_by_email.update(
            {
                "clerk_user_id": clerk_user_id,
                "name": name,
                "picture": picture,
                "auth_provider": "clerk",
                "updated_at": utc_now_iso(),
            }
        )
        return await store.save_user(existing_by_email)

    user = User(email=email, name=name, role="student")
    user_dict = user.model_dump()
    user_dict.update(
        {
            "clerk_user_id": clerk_user_id,
            "picture": picture,
            "auth_provider": "clerk",
            "created_at": user_dict["created_at"].isoformat(),
            "updated_at": utc_now_iso(),
        }
    )
    return await store.save_user(user_dict)


def _role_matches_portal(user_role: str, requested_role: Optional[str]) -> bool:
    """Allow portal-specific sign-in while keeping admin/faculty hierarchy intact."""
    if not requested_role or requested_role == "student":
        return True
    if requested_role == "faculty":
        return user_role in {"faculty", "admin"}
    if requested_role == "admin":
        return user_role == "admin"
    return False


def _is_supabase_connectivity_error(exc: Exception) -> bool:
    """Detect network-level failures so we do not misreport them as bad credentials."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError)):
        return True

    message = str(exc).lower()
    connectivity_markers = [
        "connection refused",
        "actively refused",
        "timed out",
        "network is unreachable",
        "temporary failure in name resolution",
        "nodename nor servname provided",
        "getaddrinfo failed",
    ]
    return any(marker in message for marker in connectivity_markers)


async def sync_clerk_user(clerk_claims: dict) -> Optional[dict]:
    """Upsert a Clerk-authenticated user into the local database."""
    clerk_user_id = clerk_claims.get("sub")
    if not clerk_user_id:
        return None

    existing_user = await store.get_user_by_clerk_user_id(clerk_user_id)
    if existing_user:
        return existing_user

    clerk_user = await fetch_clerk_user(clerk_user_id)
    if not clerk_user:
        return None

    email = _extract_primary_email(clerk_user)
    first_name = clerk_user.get("first_name") or ""
    last_name = clerk_user.get("last_name") or ""
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    name = full_name or clerk_user.get("username") or email.split("@")[0] or "User"
    image_url = clerk_user.get("image_url")

    return await upsert_clerk_user_profile(clerk_user_id, email, name, image_url)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """Get the current authenticated user from Clerk or legacy JWT token."""
    if credentials:
        supabase_auth_user = await fetch_supabase_user(credentials.credentials)
        if supabase_auth_user:
            user = await sync_supabase_user(supabase_auth_user)
            if user:
                return _format_current_user(user)

        clerk_payload = verify_clerk_session_token(credentials.credentials)
        if clerk_payload:
            user = await sync_clerk_user(clerk_payload)
            if user:
                return _format_current_user(user)

        user = await get_current_user_from_token(credentials)
        if user:
            return user
    
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_role_dep(allowed_roles: list):
    """Dependency to require specific roles for access"""
    async def role_checker(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> dict:
        user = await get_current_user(request, credentials)
        
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required roles: {allowed_roles}"
            )
        
        return user
    
    return role_checker


def _default_chat_result() -> dict:
    """Return a safe default response for chat failures."""
    return {
        "response": (
            "I'm sorry, but I couldn't generate a full answer right now. "
            "Please try again in a moment."
        ),
        "sources": [],
        "images": [],
        "artifacts": [],
    }


def _has_good_sources(source_payload: list) -> bool:
    """Check whether retrieved sources are strong enough to skip web fallback."""
    source_scores = [source.get("relevance_score", 0) for source in source_payload]
    best_source_score = max(source_scores, default=0)
    return bool(source_payload) and best_source_score >= 0.45


def _build_source_citations(source_payload: list) -> List[SourceCitation]:
    """Convert raw source payloads into API models."""
    return [
        SourceCitation(
            document_id=source["document_id"],
            document_title=source["document_title"],
            chunk_text=source["chunk_text"],
            relevance_score=source["relevance_score"]
        )
        for source in source_payload
    ]


def _should_use_large_pdf_pipeline(file_type: str, file_size: int) -> bool:
    """Route large PDFs through the stronger hybrid RAG indexer automatically."""
    size_mb = max(file_size / (1024 * 1024), 0.0)
    return file_type == "pdf" and size_mb >= 8


async def _index_large_pdf_document(
    *,
    document_id: str,
    title: str,
    file_content: bytes,
) -> Dict:
    """Index a large PDF into the shared high-capacity collection."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name

        result = await asyncio.to_thread(
            index_pdf_document,
            temp_path,
            LARGE_PDF_COLLECTION_NAME,
            document_id=document_id,
            document_title=title,
        )
        return result
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


async def _resolve_large_pdf_chat_result(message: str) -> Optional[dict]:
    """Use the large-PDF hybrid index when it has better-grounded material."""
    documents = await store.list_documents(limit=200)
    candidate_collections = {
        _document_collection_name(document)
        for document in documents
        if document.get("status") == "indexed" and document.get("doc_type") == "pdf"
    }
    if large_pdf_collection_has_data(LARGE_PDF_COLLECTION_NAME):
        candidate_collections.add(LARGE_PDF_COLLECTION_NAME)

    best_payload: Optional[dict] = None
    best_confidence = 0.0

    for collection_name in candidate_collections:
        if not collection_name or not large_pdf_collection_has_data(collection_name):
            continue

        try:
            payload = await asyncio.to_thread(
                answer_large_pdf_question,
                message,
                collection_name,
            )
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("Large PDF RAG fallback failed for %s in %s: %s", message, collection_name, exc)
            continue

        if not payload or payload.get("response") == "Not enough information found":
            continue

        confidence = float(payload.get("confidence") or 0.0)
        if confidence >= best_confidence:
            best_payload = payload
            best_confidence = confidence

    if not best_payload:
        return None

    return {
        "response": best_payload.get("response", ""),
        "sources": best_payload.get("sources", []),
        "images": [],
        "artifacts": [],
    }


def _store_document_images(document_id: str, image_payload: list) -> List[dict]:
    """Persist extracted document images and return lightweight metadata refs."""
    stored_images = []

    for index, image in enumerate(image_payload[:4], start=1):
        content = image.get("content")
        content_type = image.get("content_type", "image/jpeg")
        filename = image.get("filename", f"image-{index}.jpg")
        sanitized_name = f"media-{index}-{Path(filename).name}".replace(" ", "-")

        if content:
            storage_path = f"{document_id}/media/{sanitized_name}"
            uploaded_path = upload_bytes(storage_path, content, content_type, SUPABASE_STORAGE_BUCKET)
            if not uploaded_path:
                continue

            stored_images.append(
                {
                    "storage_bucket": SUPABASE_STORAGE_BUCKET,
                    "storage_path": uploaded_path,
                    "content_type": content_type,
                    "alt": image.get("alt", ""),
                    "source_title": image.get("source_title", ""),
                    "origin": "document",
                }
            )
            continue

        direct_url = (image.get("url") or "").strip()
        if direct_url:
            stored_images.append(
                {
                    "url": direct_url,
                    "alt": image.get("alt", ""),
                    "source_title": image.get("source_title", ""),
                    "source_url": image.get("source_url"),
                    "origin": image.get("origin", "website"),
                }
            )

    return stored_images


def _build_chat_images(image_payload: list) -> List[ChatImage]:
    """Resolve image refs into API models that the frontend can render directly."""
    chat_images: List[ChatImage] = []
    seen = set()

    for image in image_payload[:4]:
        key = image.get("storage_path") or image.get("url")
        if not key or key in seen:
            continue

        image_url = None
        if image.get("storage_path"):
            try:
                raw_bytes = download_bytes(
                    image["storage_path"],
                    bucket_name=image.get("storage_bucket") or SUPABASE_STORAGE_BUCKET,
                )
                if raw_bytes:
                    content_type = image.get("content_type", "image/jpeg")
                    encoded = base64.b64encode(raw_bytes).decode("ascii")
                    image_url = f"data:{content_type};base64,{encoded}"
            except Exception as exc:
                logger.debug("Could not resolve stored image %s: %s", image.get("storage_path"), exc)
        else:
            image_url = (image.get("url") or "").strip()

        if not image_url:
            continue

        chat_images.append(
            ChatImage(
                url=image_url,
                alt=image.get("alt", ""),
                source_title=image.get("source_title", ""),
                source_url=image.get("source_url"),
                origin=image.get("origin", "document"),
            )
        )
        seen.add(key)

    return chat_images


def _slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return cleaned or "scholar-pulse-export"


def _truncate_title(value: str, limit: int = 72) -> str:
    clean = DocumentProcessor.clean_text(value or "")
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit].rstrip()}..."


def _build_pdf_artifact(content: str, title: Optional[str] = None, generated_from_role: str = "assistant") -> ChatArtifact:
    """Generate a lightweight text PDF artifact and return it as a chat-ready payload."""
    try:
        import fitz
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="PDF generation dependency is unavailable") from exc

    normalized_content = DocumentProcessor.clean_text(content or "").strip()
    if not normalized_content:
        raise HTTPException(status_code=400, detail="There is no message content available to convert into a PDF")

    export_title = _truncate_title(title or normalized_content.split("\n", 1)[0] or "Scholar Pulse Export")
    filename = f"{_slugify_filename(export_title)}.pdf"

    doc = fitz.open()
    page_width = 595
    page_height = 842
    margin_x = 54
    margin_top = 66
    line_height = 18
    body_font_size = 12
    title_font_size = 20
    lines_per_page = 37

    wrapped_lines: List[str] = []
    for paragraph in normalized_content.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(textwrap.wrap(paragraph, width=86) or [""])

    current_index = 0
    page_number = 1
    while current_index < len(wrapped_lines) or page_number == 1:
        page = doc.new_page(width=page_width, height=page_height)
        page.insert_text((margin_x, margin_top), export_title, fontsize=title_font_size, fontname="helv", fill=(0.043, 0.098, 0.235))
        page.insert_text((margin_x, margin_top + 24), "Generated by Scholar Pulse", fontsize=10, fontname="helv", fill=(0.38, 0.44, 0.56))

        y = margin_top + 64
        visible_lines = lines_per_page - (3 if page_number == 1 else 0)
        for _ in range(max(visible_lines, 1)):
            if current_index >= len(wrapped_lines):
                break

            line = wrapped_lines[current_index]
            if line:
                page.insert_text((margin_x, y), line, fontsize=body_font_size, fontname="helv", fill=(0.133, 0.192, 0.31))
            y += line_height
            current_index += 1

        page.insert_text(
            (page_width - margin_x - 42, page_height - 28),
            str(page_number),
            fontsize=10,
            fontname="helv",
            fill=(0.44, 0.5, 0.64),
        )
        page_number += 1

        if current_index >= len(wrapped_lines):
            break

    pdf_bytes = doc.tobytes()
    doc.close()
    data_url = f"data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode('ascii')}"

    return ChatArtifact(
        title=export_title,
        filename=filename,
        data_url=data_url,
        text_content=normalized_content,
        generated_from_role=generated_from_role if generated_from_role in {"user", "assistant", "system"} else "assistant",
    )


def _is_pdf_export_request(message: str) -> bool:
    return bool(PDF_EXPORT_PATTERN.search((message or "").strip()))


def _resolve_pdf_export_source(message: str, conversation_history: Optional[List[Dict]]) -> Optional[Dict[str, str]]:
    """Pick the most relevant recent message for a natural-language PDF export request."""
    history = conversation_history or []
    lowered = (message or "").lower()

    preferred_role = "assistant"
    if any(token in lowered for token in ("my message", "my text", "what i wrote", "user message", "my last", "my previous", "my latest")):
        preferred_role = "user"
    elif any(
        token in lowered
        for token in (
            "your response",
            "your answer",
            "assistant message",
            "reply above",
            "this answer",
            "this response",
            "last answer",
            "latest answer",
            "event summary",
            "this event",
            "this summary",
        )
    ):
        preferred_role = "assistant"

    for role in ([preferred_role, "assistant", "user", "system"] if preferred_role == "assistant" else [preferred_role, "assistant", "user"]):
        for item in reversed(history):
            if item.get("role") != role:
                continue
            content = DocumentProcessor.clean_text(item.get("content", "")).strip()
            if not content:
                continue
            return {
                "role": role,
                "content": content,
            }

    return None


def _build_pdf_chat_result(source_message: Dict[str, str]) -> dict:
    role = source_message.get("role", "assistant")
    content = source_message.get("content", "")
    title_prefix = "Scholar Pulse Reply" if role == "assistant" else "Scholar Pulse Note"
    artifact = _build_pdf_artifact(content, title=f"{title_prefix} PDF", generated_from_role=role)
    return {
        "response": (
            f"I converted the latest {role} message into a PDF.\n\n"
            "Use the controls below to view it, edit the text, or download the file."
        ),
        "sources": [],
        "images": [],
        "artifacts": [artifact],
    }


def _normalize_document_filename(value: Optional[str]) -> str:
    """Normalize a filename for duplicate detection."""
    return (value or "").strip().lower()


def _normalize_source_url(value: Optional[str]) -> str:
    """Normalize a URL for duplicate detection."""
    normalized = (value or "").strip().lower()
    if normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


async def _ensure_chat_session(user_id: str, session_id: Optional[str]) -> str:
    """Return an existing session id or create a new one."""
    if session_id:
        return session_id

    session = ChatSession(user_id=user_id)
    session_dict = session.model_dump()
    session_dict["created_at"] = session_dict["created_at"].isoformat()
    session_dict["updated_at"] = session_dict["updated_at"].isoformat()
    await store.create_chat_session(session_dict)
    return session.id


async def _get_recent_conversation_history(user_id: str, session_id: str) -> List[Dict]:
    """Load a small amount of recent chat history for multi-turn prompting."""
    session = await store.get_chat_session(session_id, user_id)
    if not session:
        return []
    return (session.get("messages") or [])[-6:]


async def _persist_chat_turn(
    *,
    user_id: str,
    session_id: str,
    message: str,
    response_text: str,
    sources: List[SourceCitation],
    voice_input: bool,
    processing_time_ms: int,
    is_web_fallback: bool,
):
    """Persist analytics and session history for a completed chat turn."""
    query_log = QueryLog(
        user_id=user_id,
        query=message,
        response_length=len(response_text),
        sources_count=len(sources),
        voice_input=voice_input,
        processing_time_ms=processing_time_ms
    )
    log_dict = query_log.model_dump()
    log_dict["created_at"] = log_dict["created_at"].isoformat()
    log_dict["is_web_fallback"] = is_web_fallback
    await store.create_query_log(log_dict)
    await store.append_chat_turn(
        session_id=session_id,
        message=message,
        response_text=response_text,
        is_web_fallback=is_web_fallback,
    )


def _normalize_answer_mode(answer_mode: Optional[str]) -> str:
    """Normalize the requested answer source."""
    return "internet" if (answer_mode or "").strip().lower() == "internet" else "database"


async def _resolve_internet_chat_result(
    message: str,
    conversation_history: Optional[List[Dict]] = None,
) -> tuple[dict, bool]:
    """Resolve a DuckDuckGo-backed internet answer."""
    search_results = await WebSearchFallback.search(message)
    if not search_results:
        return await get_web_search_fallback(message), True

    image_payload = await WebSearchFallback.build_image_payload(search_results)
    return {
        "response": rag_engine.generate_web_response(
            message,
            search_results,
            conversation_history=conversation_history,
        ),
        "sources": WebSearchFallback.build_sources(search_results),
        "images": image_payload,
    }, True


async def _resolve_event_chat_result(
    message: str,
    conversation_history: Optional[List[Dict]] = None,
) -> Optional[tuple[dict, bool]]:
    """Resolve event/news questions from the official KRMU happenings feed."""
    if not KRMUEventsFeed.is_event_query(message):
        return None

    try:
        events = await KRMUEventsFeed.search_events(message, conversation_history=conversation_history, max_events=3)
    except Exception as exc:
        logger.exception("KRMU events pipeline failed for message %s: %s", message, exc)
        return None

    if not events:
        return None

    return (
        {
            "response": KRMUEventsFeed.summarize_events(
                message,
                events,
                conversation_history=conversation_history,
            ),
            "sources": KRMUEventsFeed.build_sources(events),
            "images": KRMUEventsFeed.build_image_payload(events),
        },
        True,
    )


async def _resolve_chat_result(
    message: str,
    answer_mode: str = "database",
    conversation_history: Optional[List[Dict]] = None,
) -> tuple[dict, bool]:
    """Resolve a non-streaming chat result for the selected source mode."""
    normalized_mode = _normalize_answer_mode(answer_mode)

    if _is_pdf_export_request(message):
        source_message = _resolve_pdf_export_source(message, conversation_history)
        if source_message:
            return _build_pdf_chat_result(source_message), False
        return {
            "response": "I couldn't find a recent message to convert yet. Ask a question first, then say `convert this message to pdf`.",
            "sources": [],
            "images": [],
            "artifacts": [],
        }, False

    if normalized_mode == "internet":
        try:
            return await _resolve_internet_chat_result(message, conversation_history=conversation_history)
        except Exception as exc:
            logger.exception("Internet chat pipeline failed for message %s: %s", message, exc)
            return {
                "response": (
                    "I ran into a temporary issue while checking DuckDuckGo results. "
                    "Please try again in a moment."
                ),
                "sources": [],
            "images": [],
            "artifacts": [],
        }, True

    is_web_fallback = False
    rag_result = _default_chat_result()

    event_result = await _resolve_event_chat_result(message, conversation_history=conversation_history)
    if event_result:
        return event_result

    try:
        rag_result = rag_engine.chat(message, conversation_history=conversation_history)

        if not _has_good_sources(rag_result.get("sources", [])):
            large_pdf_result = await _resolve_large_pdf_chat_result(message)
            if large_pdf_result and _has_good_sources(large_pdf_result.get("sources", [])):
                rag_result = large_pdf_result
            else:
                rag_result = {
                    "response": (
                        "I couldn't find a sufficiently grounded answer in the indexed knowledge base. "
                        "Please rephrase the question or upload/seed more relevant documents."
                    ),
                    "sources": rag_result.get("sources", []),
                    "images": rag_result.get("images", []),
                    "artifacts": rag_result.get("artifacts", []),
                }
    except Exception as exc:
        logger.exception("Chat pipeline failed for message %s: %s", message, exc)
        rag_result = {
            "response": (
                "I ran into a temporary issue while checking the indexed knowledge base. "
                "Please try again in a moment."
            ),
            "sources": [],
            "images": [],
            "artifacts": [],
        }

    return rag_result, is_web_fallback


def _sse_event(payload: dict) -> str:
    """Format a Server-Sent Event payload."""
    return f"data: {json.dumps(payload)}\n\n"


async def _write_upload_to_temp_file(file: UploadFile) -> tuple[str, int]:
    """Persist an uploaded file to a temp path without holding it all in RAM."""
    suffix = Path(file.filename or "upload.bin").suffix or ".bin"
    total_size = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = temp_file.name
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            temp_file.write(chunk)
            total_size += len(chunk)
    await file.close()
    return temp_path, total_size


def _estimate_pdf_part_ranges(pdf_path: str, file_size: int, max_part_bytes: int) -> List[tuple[int, int]]:
    """Split a PDF into page ranges sized for Supabase's file limits."""
    with fitz.open(pdf_path) as document:
        total_pages = document.page_count

    if total_pages <= 0:
        return [(0, 0)]

    estimated_parts = max(1, math.ceil(file_size / max(max_part_bytes, 1)))
    pages_per_part = max(1, math.ceil(total_pages / estimated_parts))
    ranges: List[tuple[int, int]] = []
    for start_page in range(0, total_pages, pages_per_part):
        end_page = min(total_pages - 1, start_page + pages_per_part - 1)
        ranges.append((start_page, end_page))
    return ranges


def _split_pdf_to_supabase_parts(document_id: str, pdf_path: str, content_type: str) -> Dict[str, Any]:
    """Split a large PDF into page-range parts and upload each part to Supabase Storage."""
    ranges = _estimate_pdf_part_ranges(pdf_path, os.path.getsize(pdf_path), SUPABASE_MAX_PART_BYTES)
    uploaded_parts: List[Dict[str, Any]] = []

    with fitz.open(pdf_path) as source_document:
        total_pages = source_document.page_count
        for part_index, (start_page, end_page) in enumerate(ranges, start=1):
            part_document = fitz.open()
            part_document.insert_pdf(source_document, from_page=start_page, to_page=end_page)
            part_bytes = part_document.tobytes(garbage=4, deflate=True)
            part_document.close()

            part_name = f"{document_id}_part_{part_index}.pdf"
            storage_path = f"{document_id}/{part_name}"
            upload_result = upload_bytes(
                storage_path,
                part_bytes,
                content_type or "application/pdf",
                SUPABASE_STORAGE_BUCKET,
            )
            if not upload_result:
                raise RuntimeError(f"Failed to upload split PDF part {part_index}")

            uploaded_parts.append(
                {
                    "storage_path": storage_path,
                    "filename": part_name,
                    "part_index": part_index,
                    "start_page": start_page + 1,
                    "end_page": end_page + 1,
                    "file_size": len(part_bytes),
                }
            )

    return {"parts": uploaded_parts, "page_count": total_pages}


def _upload_document_to_storage(
    document_id: str,
    file_path: str,
    filename: str,
    content_type: str,
    doc_type: str,
) -> Dict[str, Any]:
    """Upload either a single file or split PDF parts to Supabase Storage."""
    file_size = os.path.getsize(file_path)
    if doc_type == "pdf" and file_size > SUPABASE_SPLIT_THRESHOLD_BYTES:
        split_payload = _split_pdf_to_supabase_parts(document_id, file_path, content_type)
        return {
            "storage_path": None,
            "total_parts": len(split_payload["parts"]),
            "processing_metadata": {
                "storage_parts": split_payload["parts"],
                "page_count": split_payload["page_count"],
            },
        }

    sanitized_name = filename.replace("\\", "_").replace("/", "_")
    storage_path = f"{document_id}/{sanitized_name}"
    payload_bytes = Path(file_path).read_bytes()
    upload_result = upload_bytes(
        storage_path,
        payload_bytes,
        content_type or "application/octet-stream",
        SUPABASE_STORAGE_BUCKET,
    )
    if not upload_result:
        raise RuntimeError("Failed to upload file to Supabase Storage")

    page_count = 0
    if doc_type == "pdf":
        with fitz.open(file_path) as document:
            page_count = document.page_count

    return {
        "storage_path": storage_path,
        "total_parts": 1,
        "processing_metadata": {
            "storage_parts": [
                {
                    "storage_path": storage_path,
                    "filename": filename,
                    "part_index": 1,
                    "start_page": 1,
                    "end_page": page_count or None,
                    "file_size": file_size,
                }
            ],
            "page_count": page_count,
        },
    }


def _download_document_payload_to_temp(document: Dict[str, Any], emit: Optional[Any] = None) -> str:
    """Download a document's storage payload and reassemble split PDFs on local disk."""
    metadata = document.get("processing_metadata") or {}
    storage_parts = list(metadata.get("storage_parts") or [])
    if not storage_parts and document.get("storage_path"):
        storage_parts = [
            {
                "storage_path": document["storage_path"],
                "filename": document.get("filename"),
                "part_index": 1,
            }
        ]
    if not storage_parts:
        raise RuntimeError("No storage payload found for this document")

    temp_dir = tempfile.mkdtemp(prefix=f"doc-{document['id']}-")
    downloaded_paths: List[str] = []
    total_parts = max(1, len(storage_parts))

    for index, part in enumerate(sorted(storage_parts, key=lambda item: item.get("part_index", 0)), start=1):
        part_bytes = download_bytes(part.get("storage_path"), SUPABASE_STORAGE_BUCKET)
        if not part_bytes:
            raise RuntimeError(f"Failed to download storage part {index}")
        part_path = Path(temp_dir) / (part.get("filename") or f"part-{index}.pdf")
        part_path.write_bytes(part_bytes)
        downloaded_paths.append(str(part_path))
        if emit:
            emit(
                {
                    "stage": "downloading",
                    "progress": min(10, int((index / total_parts) * 10)),
                    "part": index,
                    "total_parts": total_parts,
                }
            )

    if document.get("doc_type") != "pdf" or len(downloaded_paths) == 1:
        return downloaded_paths[0]

    merged_path = Path(temp_dir) / f"{document['id']}_merged.pdf"
    merged_pdf = fitz.open()
    try:
        for index, part_path in enumerate(downloaded_paths, start=1):
            with fitz.open(part_path) as part_document:
                merged_pdf.insert_pdf(part_document)
            if emit:
                emit(
                    {
                        "stage": "assembling",
                        "progress": 10 + min(10, int((index / len(downloaded_paths)) * 10)),
                        "part": index,
                        "total_parts": len(downloaded_paths),
                    }
                )
        merged_pdf.save(str(merged_path), garbage=4, deflate=True)
    finally:
        merged_pdf.close()

    return str(merged_path)


def _process_pdf_job_sync(document: Dict[str, Any], emit: Optional[Any] = None) -> Dict[str, Any]:
    """Run the SSE-driven PDF processing path entirely on the backend service."""
    pdf_path = _download_document_payload_to_temp(document, emit=emit)
    temp_dir = str(Path(pdf_path).parent)
    collection_name = large_pdf_job_collection_name(document["id"])

    try:
        def _emit(payload: Dict[str, Any]) -> None:
            if emit:
                emit(payload)

        pages = extract_large_pdf_pages(
            pdf_path,
            progress_callback=_emit,
            batch_size=SSE_PAGE_BATCH_SIZE,
        )
        gc.collect()

        chunks = chunk_large_pdf_document(
            pages,
            progress_callback=_emit,
        )
        decorated_chunks = []
        normalized_title = (document.get("title") or document.get("filename") or "Document").strip()
        for index, chunk in enumerate(chunks):
            metadata = dict(chunk.get("metadata") or {})
            metadata["document_id"] = document["id"]
            metadata["document_title"] = normalized_title
            metadata["source_file"] = normalized_title
            metadata["job_id"] = document["id"]
            decorated_chunks.append(
                {
                    "id": f"{document['id']}-{index}",
                    "text": chunk["text"],
                    "metadata": metadata,
                }
            )

        result = embed_large_pdf_chunks(
            decorated_chunks,
            collection_name,
            progress_callback=_emit,
        )
        gc.collect()
        result["page_count"] = len(pages)
        result["collection_name"] = collection_name
        return result
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _process_non_pdf_job_sync(document: Dict[str, Any], emit: Optional[Any] = None) -> Dict[str, Any]:
    """Fallback synchronous processing path for non-PDF uploads."""
    local_path = _download_document_payload_to_temp(document, emit=emit)
    temp_dir = str(Path(local_path).parent)
    try:
        file_bytes = Path(local_path).read_bytes()
        file_type = document.get("doc_type", "txt")
        title = document.get("title") or document.get("filename") or "Document"

        if emit:
            emit({"stage": "extracting", "progress": 25})
        result = DocumentProcessor.process_file(file_bytes, file_type)
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "Failed to process document")

        if emit:
            emit({"stage": "chunking", "progress": 60, "chunks": len(result.get("chunks") or [])})
        chunk_count = rag_engine.add_document_chunks(
            document_id=document["id"],
            document_title=title,
            chunks=result["chunks"],
            metadata={
                "doc_type": file_type,
                "job_id": document["id"],
            },
        )
        if emit:
            emit({"stage": "embedding", "progress": 90})

        return {
            "collection_name": rag_engine.collection_name,
            "chunks_indexed": chunk_count,
            "page_count": 0,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _document_collection_name(document: Dict[str, Any]) -> str:
    """Resolve the Chroma collection name for a processed document."""
    metadata = document.get("processing_metadata") or {}
    return (
        metadata.get("collection_name")
        or (large_pdf_job_collection_name(document["id"]) if document.get("doc_type") == "pdf" else rag_engine.collection_name)
    )


# ==================== Auth Routes ====================

@api_router.get("/ping")
async def ping() -> Dict[str, str]:
    """
    Lightweight keep-alive endpoint for Render free tier.
    Point UptimeRobot or a 10-minute frontend heartbeat here to reduce cold starts.
    """
    return {"status": "alive"}

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    """Register a new user"""
    requested_role = user_data.role if user_data.role == "student" else "student"

    if has_supabase_config():
        try:
            existing_user = await store.get_user_by_email(user_data.email)
            if existing_user:
                raise HTTPException(status_code=400, detail="Email already registered")

            supabase_admin = get_supabase_admin_client()
            supabase_public = get_supabase_public_client()
            if not supabase_admin or not supabase_public:
                raise HTTPException(status_code=500, detail="Supabase clients are not configured")

            created = await asyncio.to_thread(
                lambda: supabase_admin.auth.admin.create_user(
                    {
                        "email": user_data.email,
                        "password": user_data.password,
                        "email_confirm": True,
                        "user_metadata": {
                            "name": user_data.name,
                            "role": requested_role,
                        },
                    }
                )
            )
            created_user = getattr(created, "user", None)
            if hasattr(created_user, "model_dump"):
                created_user = created_user.model_dump()
            if not created_user:
                raise HTTPException(status_code=400, detail="Supabase user creation returned no profile")

            profile = await sync_supabase_user(created_user)
            if not profile:
                raise HTTPException(status_code=400, detail="Unable to create application profile")

            auth_response = await asyncio.to_thread(
                lambda: supabase_public.auth.sign_in_with_password(
                    {"email": user_data.email, "password": user_data.password}
                )
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Supabase register flow failed for %s: %s", user_data.email, exc)
            if _is_supabase_connectivity_error(exc):
                raise HTTPException(
                    status_code=503,
                    detail="Supabase authentication service is unreachable. Check your network or Supabase project settings.",
                ) from exc
            raise HTTPException(status_code=400, detail="Unable to create Supabase user") from exc

        session = getattr(auth_response, "session", None)
        access_token = getattr(session, "access_token", None)
        if not access_token:
            raise HTTPException(status_code=400, detail="Supabase did not return an access token")

        return TokenResponse(
            access_token=access_token,
            user=UserResponse(
                id=profile["id"],
                email=profile["email"],
                name=profile["name"],
                role=profile.get("role", "student"),
                is_active=profile.get("is_active", True),
            ),
        )

    # Allow first-time password setup for migrated accounts that exist without a password hash.
    existing = await store.get_user_by_email(user_data.email)
    if existing:
        if existing.get("password_hash"):
            raise HTTPException(status_code=400, detail="Email already registered")

        existing.update(
            {
                "name": user_data.name or existing.get("name") or user_data.email,
                "password_hash": hash_password(user_data.password),
                "auth_provider": "local",
                "is_active": True,
            }
        )
        updated_user = await store.save_user(existing)
        token = create_access_token({
            "sub": updated_user["id"],
            "email": updated_user["email"],
            "name": updated_user["name"],
            "role": updated_user.get("role", "student")
        })

        return TokenResponse(
            access_token=token,
            user=UserResponse(
                id=updated_user["id"],
                email=updated_user["email"],
                name=updated_user["name"],
                role=updated_user.get("role", "student"),
                is_active=updated_user.get("is_active", True)
            )
        )
    
    # Create user
    user = User(
        email=user_data.email,
        name=user_data.name,
        role=requested_role
    )
    
    user_dict = user.model_dump()
    user_dict["password_hash"] = hash_password(user_data.password)
    user_dict["created_at"] = user_dict["created_at"].isoformat()
    
    await store.save_user(user_dict)
    
    # Create token
    token = create_access_token({
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role
    })
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            is_active=user.is_active
        )
    )


@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """Login and get access token"""
    if has_supabase_config():
        try:
            supabase_public = get_supabase_public_client()
            if not supabase_public:
                raise HTTPException(status_code=500, detail="Supabase public client is not configured")

            auth_response = await asyncio.to_thread(
                lambda: supabase_public.auth.sign_in_with_password(
                    {"email": credentials.email, "password": credentials.password}
                )
            )
            session = getattr(auth_response, "session", None)
            user_payload = getattr(auth_response, "user", None)
            if hasattr(user_payload, "model_dump"):
                user_payload = user_payload.model_dump()

            access_token = getattr(session, "access_token", None)
            if not access_token or not user_payload:
                raise HTTPException(status_code=401, detail="Invalid email or password")

            user = await sync_supabase_user(user_payload)
            if not user:
                raise HTTPException(status_code=400, detail="Unable to load user profile")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Supabase login failed for %s: %s", credentials.email, exc)
            if _is_supabase_connectivity_error(exc):
                raise HTTPException(
                    status_code=503,
                    detail="Supabase authentication service is unreachable. Check your network or Supabase project settings.",
                ) from exc
            raise HTTPException(status_code=401, detail="Invalid email or password") from exc

        return TokenResponse(
            access_token=access_token,
            user=UserResponse(
                id=user["id"],
                email=user["email"],
                name=user["name"],
                role=user.get("role", "student"),
                is_active=user.get("is_active", True),
            ),
        )

    user = await store.get_user_by_email(credentials.email)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("password_hash"):
        raise HTTPException(
            status_code=400,
            detail="This account does not have a password yet. Use sign up once to set your password."
        )

    if not verify_password(credentials.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_access_token({
        "sub": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"]
    })
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            name=user["name"],
            role=user["role"],
            is_active=user.get("is_active", True)
        )
    )


@api_router.get("/auth/me")
async def get_me(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get current user profile"""
    user = await get_current_user(request, credentials)
    
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "picture": user.get("picture"),
        "is_active": True
    }


@api_router.post("/auth/clerk-exchange", response_model=TokenResponse)
async def clerk_exchange(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Exchange a Clerk-authenticated frontend profile for a local app JWT."""
    body = await request.json()
    clerk_user_id = body.get("clerk_user_id")
    email = body.get("email")
    name = body.get("name")
    picture = body.get("picture")
    requested_role = body.get("requested_role")

    existing_user = None
    if clerk_user_id:
        existing_user = await store.get_user_by_clerk_user_id(clerk_user_id)
        if existing_user:
            email = email or existing_user.get("email")
            name = name or existing_user.get("name")
            picture = picture or existing_user.get("picture")

    clerk_payload = None
    if credentials:
        clerk_payload = verify_clerk_session_token(credentials.credentials)

    if clerk_payload:
        if clerk_payload.get("sub") != clerk_user_id:
            raise HTTPException(status_code=403, detail="Clerk user mismatch")
    elif not existing_user:
        clerk_user = await fetch_clerk_user(clerk_user_id)
        if clerk_user:
            verified_email = _extract_primary_email(clerk_user)
            email = email or verified_email
            name = name or " ".join(
                part for part in [clerk_user.get("first_name") or "", clerk_user.get("last_name") or ""]
                if part
            ).strip() or clerk_user.get("username") or email
            picture = picture or clerk_user.get("image_url")

            if verified_email and email and verified_email.lower() != email.lower():
                raise HTTPException(status_code=403, detail="Clerk email mismatch")
        else:
            logger.warning(
                "Proceeding with unverified Clerk exchange for %s because Clerk API lookup failed",
                clerk_user_id
            )
    else:
        logger.info("Using existing mapped Clerk user %s without remote Clerk lookup", clerk_user_id)

    if not clerk_user_id or not email:
        raise HTTPException(status_code=400, detail="Missing Clerk profile data")

    user = await upsert_clerk_user_profile(
        clerk_user_id=clerk_user_id,
        email=email,
        name=name or email,
        picture=picture,
        requested_role=requested_role,
    )

    if not user:
        raise HTTPException(status_code=400, detail="Unable to exchange Clerk profile")

    if requested_role in {"faculty", "admin"} and not _role_matches_portal(
        user.get("role", "student"),
        requested_role
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "This portal requires a pre-approved "
                f"{'teacher' if requested_role == 'faculty' else 'admin'} account."
            )
        )

    token = create_access_token({
        "sub": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user.get("role", "student")
    })

    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            name=user["name"],
            role=user.get("role", "student"),
            is_active=user.get("is_active", True)
        )
    )


@api_router.post("/auth/sync")
async def sync_auth_profile(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Create or update an application profile from the signed-in auth provider."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    supabase_auth_user = await fetch_supabase_user(credentials.credentials)
    if supabase_auth_user:
        user = await sync_supabase_user(supabase_auth_user)
        if not user:
            raise HTTPException(status_code=400, detail="Unable to sync Supabase profile")

        return {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "picture": user.get("picture"),
            "is_active": user.get("is_active", True),
        }

    clerk_payload = verify_clerk_session_token(credentials.credentials)
    if not clerk_payload:
        raise HTTPException(status_code=401, detail="Invalid auth session")

    body = await request.json()
    clerk_user_id = body.get("clerk_user_id")
    email = body.get("email")
    name = body.get("name")
    picture = body.get("picture")

    if clerk_payload.get("sub") != clerk_user_id:
        raise HTTPException(status_code=403, detail="Clerk user mismatch")

    user = await upsert_clerk_user_profile(
        clerk_user_id=clerk_user_id,
        email=email,
        name=name or email,
        picture=picture,
    )

    if not user:
        raise HTTPException(status_code=400, detail="Unable to sync user profile")

    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "picture": user.get("picture"),
        "is_active": user.get("is_active", True),
    }


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    """Frontend handles Clerk sign-out; backend logout is stateless."""
    return {"message": "Logged out successfully"}


# ==================== Chat Routes ====================

@api_router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Send a chat message and get RAG-powered response"""
    current_user = await get_current_user(request, credentials)
    start_time = time.time()
    session_id = await _ensure_chat_session(current_user["id"], chat_request.session_id)
    conversation_history = await _get_recent_conversation_history(current_user["id"], session_id)
    answer_mode = _normalize_answer_mode(chat_request.answer_mode)

    rag_result, is_web_fallback = await _resolve_chat_result(
        chat_request.message,
        answer_mode=answer_mode,
        conversation_history=conversation_history,
    )
    
    # Format sources
    sources = [
        SourceCitation(
            document_id=s["document_id"],
            document_title=s["document_title"],
            chunk_text=s["chunk_text"],
            relevance_score=s["relevance_score"]
        )
        for s in rag_result.get("sources", [])
    ]
    images = _build_chat_images(rag_result.get("images", []))
    artifacts = rag_result.get("artifacts", [])
    
    # Log query for analytics
    processing_time = int((time.time() - start_time) * 1000)
    await _persist_chat_turn(
        user_id=current_user["id"],
        session_id=session_id,
        message=chat_request.message,
        response_text=rag_result["response"],
        sources=sources,
        voice_input=chat_request.voice_input,
        processing_time_ms=processing_time,
        is_web_fallback=is_web_fallback,
    )
    
    return ChatResponse(
        response=rag_result["response"],
        sources=sources,
        images=images,
        artifacts=artifacts,
        session_id=session_id,
        voice_output=chat_request.voice_input,
        answer_mode=answer_mode,
    )


@api_router.post("/chat/export-pdf", response_model=PdfExportResponse)
async def export_chat_pdf(
    request: Request,
    payload: PdfExportRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Generate or regenerate a PDF from provided chat text."""
    await get_current_user(request, credentials)
    artifact = _build_pdf_artifact(
        payload.content,
        title=payload.title,
        generated_from_role=payload.generated_from_role,
    )
    return PdfExportResponse(artifact=artifact)


@api_router.post("/chat/stream")
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Stream a chat response using SSE without changing the existing frontend route."""
    current_user = await get_current_user(request, credentials)
    start_time = time.time()
    session_id = await _ensure_chat_session(current_user["id"], chat_request.session_id)
    conversation_history = await _get_recent_conversation_history(current_user["id"], session_id)
    answer_mode = _normalize_answer_mode(chat_request.answer_mode)

    if answer_mode == "internet":
        rag_result, is_web_fallback = await _resolve_chat_result(
            chat_request.message,
            answer_mode=answer_mode,
            conversation_history=conversation_history,
        )
        sources = _build_source_citations(rag_result.get("sources", []))
        images = _build_chat_images(rag_result.get("images", []))

        async def internet_stream():
            yield _sse_event(
                {
                    "type": "meta",
                    "session_id": session_id,
                    "sources": rag_result.get("sources", []),
                    "images": [image.model_dump() for image in images],
                    "is_web_fallback": is_web_fallback,
                    "answer_mode": answer_mode,
                }
            )
            yield _sse_event({"type": "delta", "content": rag_result["response"]})

            processing_time = int((time.time() - start_time) * 1000)
            await _persist_chat_turn(
                user_id=current_user["id"],
                session_id=session_id,
                message=chat_request.message,
                response_text=rag_result["response"],
                sources=sources,
                voice_input=chat_request.voice_input,
                processing_time_ms=processing_time,
                is_web_fallback=is_web_fallback,
            )
            yield _sse_event({"type": "done", "session_id": session_id, "answer_mode": answer_mode})

        return StreamingResponse(
            internet_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    retrieved_docs = rag_engine.search(chat_request.message)
    source_payload = rag_engine.format_sources(retrieved_docs)

    if not _has_good_sources(source_payload):
        rag_result, is_web_fallback = await _resolve_chat_result(
            chat_request.message,
            answer_mode=answer_mode,
            conversation_history=conversation_history,
        )
        sources = _build_source_citations(rag_result.get("sources", []))
        images = _build_chat_images(rag_result.get("images", []))

        async def fallback_stream():
            yield _sse_event(
                {
                    "type": "meta",
                    "session_id": session_id,
                    "sources": rag_result.get("sources", []),
                    "images": [image.model_dump() for image in images],
                    "is_web_fallback": is_web_fallback,
                    "answer_mode": answer_mode,
                }
            )
            yield _sse_event({"type": "delta", "content": rag_result["response"]})

            processing_time = int((time.time() - start_time) * 1000)
            await _persist_chat_turn(
                user_id=current_user["id"],
                session_id=session_id,
                message=chat_request.message,
                response_text=rag_result["response"],
                sources=sources,
                voice_input=chat_request.voice_input,
                processing_time_ms=processing_time,
                is_web_fallback=is_web_fallback,
            )
            yield _sse_event({"type": "done", "session_id": session_id, "answer_mode": answer_mode})

        return StreamingResponse(
            fallback_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    sources = _build_source_citations(source_payload)
    streamed_images = _build_chat_images(rag_engine.format_images(retrieved_docs))

    async def event_stream():
        response_parts = []

        yield _sse_event(
            {
                "type": "meta",
                "session_id": session_id,
                "sources": source_payload,
                "images": [image.model_dump() for image in streamed_images],
                "is_web_fallback": False,
                "answer_mode": answer_mode,
            }
        )

        try:
            async for chunk in rag_engine.stream_response(
                chat_request.message,
                retrieved_docs,
                conversation_history=conversation_history,
            ):
                if not chunk:
                    continue
                response_parts.append(chunk)
                yield _sse_event({"type": "delta", "content": chunk})
        except Exception as exc:
            logger.exception("Streaming chat failed for session %s: %s", session_id, exc)
            fallback_text = (
                "I ran into a temporary issue while streaming the answer. "
                "Please try again in a moment."
            )
            response_parts.append(fallback_text)
            yield _sse_event({"type": "delta", "content": fallback_text})

        response_text = "".join(response_parts).strip()
        if not response_text:
            response_text = _default_chat_result()["response"]
            yield _sse_event({"type": "delta", "content": response_text})

        processing_time = int((time.time() - start_time) * 1000)
        await _persist_chat_turn(
            user_id=current_user["id"],
            session_id=session_id,
            message=chat_request.message,
            response_text=response_text,
            sources=sources,
            voice_input=chat_request.voice_input,
            processing_time_ms=processing_time,
            is_web_fallback=False,
        )
        yield _sse_event({"type": "done", "session_id": session_id, "answer_mode": answer_mode})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@api_router.get("/chat/sessions")
async def get_chat_sessions(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get user's chat sessions"""
    current_user = await get_current_user(request, credentials)
    
    sessions = await store.list_chat_sessions(current_user["id"], limit=50)
    
    return {"sessions": sessions}


@api_router.get("/chat/sessions/{session_id}")
async def get_chat_session(
    session_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get a specific chat session"""
    current_user = await get_current_user(request, credentials)
    
    session = await store.get_chat_session(session_id, current_user["id"])
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return session


# ==================== Document Routes ====================

async def process_document_background(
    document_id: str,
    file_content: bytes,
    file_type: str,
    title: str,
    file_size: int,
):
    """Background task to process and index a document"""
    try:
        # Update status to processing
        await store.update_document(document_id, {"status": "processing"})

        if _should_use_large_pdf_pipeline(file_type, file_size):
            large_index_result = await _index_large_pdf_document(
                document_id=document_id,
                title=title,
                file_content=file_content,
            )
            await store.update_document(
                document_id,
                {
                    "status": "indexed",
                    "chunk_count": int(large_index_result.get("chunks_indexed", 0)),
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                    "error_message": None,
                },
            )
            logger.info(
                "Large PDF %s indexed into %s with %s chunks",
                document_id,
                LARGE_PDF_COLLECTION_NAME,
                large_index_result.get("chunks_indexed", 0),
            )
            return

        extraction_timeout = _document_process_timeout_seconds(file_type, file_size)
        indexing_timeout = _document_index_timeout_seconds(0, file_size)
        disable_global_timeout = _should_disable_global_document_timeout(file_type, file_size)
        
        # Process the document
        extraction_task = asyncio.to_thread(DocumentProcessor.process_file, file_content, file_type)
        if disable_global_timeout:
            logger.info(
                "Processing large %s document %s without a global extraction timeout (size=%s bytes)",
                file_type,
                document_id,
                file_size,
            )
            result = await extraction_task
        else:
            result = await asyncio.wait_for(extraction_task, timeout=extraction_timeout)
        
        if not result["success"]:
            await store.update_document(
                document_id,
                {"status": "failed", "error_message": result.get("error", "Unknown error")},
            )
            return

        image_refs = _store_document_images(document_id, result.get("images", []))
        indexing_timeout = _document_index_timeout_seconds(len(result.get("chunks") or []), file_size)

        # Add to RAG engine
        indexing_task = asyncio.to_thread(
            rag_engine.add_document_chunks,
            document_id=document_id,
            document_title=title,
            chunks=result["chunks"],
            metadata={
                "doc_type": file_type,
                "used_ocr": bool(result.get("used_ocr")),
                "ocr_engine": result.get("ocr_engine", ""),
                "ocr_quality_score": float(result.get("ocr_quality_score", 0.0) or 0.0),
                "images": image_refs,
            }
        )
        if disable_global_timeout:
            logger.info(
                "Indexing large %s document %s without a global indexing timeout (%s chunks)",
                file_type,
                document_id,
                len(result.get("chunks") or []),
            )
            chunk_count = await indexing_task
        else:
            chunk_count = await asyncio.wait_for(indexing_task, timeout=indexing_timeout)
        
        # Update document status
        await store.update_document(
            document_id,
            {
                "status": "indexed",
                "chunk_count": chunk_count,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        
        logger.info(f"Document {document_id} indexed with {chunk_count} chunks")
    except asyncio.TimeoutError:
        logger.error("Document processing timed out for %s", document_id)
        await store.update_document(
            document_id,
            {
                "status": "failed",
                "error_message": (
                    "Document processing timed out on the server. Large scanned PDFs take much longer than text-based files. "
                    "Try again after redeploying the latest backend, or split very large scanned documents into smaller parts."
                ),
            },
        )
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        await store.update_document(
            document_id,
            {"status": "failed", "error_message": str(e)},
        )


@api_router.post("/documents/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Upload and index a document"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] not in ["faculty", "admin"]:
        raise HTTPException(status_code=403, detail="Only faculty and admin can upload documents")
    
    # Determine file type
    filename = file.filename or "unknown"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    
    type_map = {
        "pdf": "pdf",
        "docx": "docx",
        "doc": "docx",
        "txt": "txt",
        "csv": "csv",
        "pptx": "pptx",
        "ppt": "pptx"
    }
    
    doc_type = type_map.get(extension)
    if not doc_type:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {extension}")
    
    temp_upload_path, file_size = await _write_upload_to_temp_file(file)

    existing_documents = await store.list_documents(limit=500)
    normalized_filename = _normalize_document_filename(filename)
    duplicate_document = next(
        (
            doc for doc in existing_documents
            if doc.get("status") != "failed"
            and doc.get("doc_type") == doc_type
            and _normalize_document_filename(doc.get("filename")) == normalized_filename
            and int(doc.get("file_size") or 0) == file_size
        ),
        None,
    )
    if duplicate_document:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This document looks like a duplicate of \"{duplicate_document.get('title', filename)}\" "
                "and is already in the knowledge base."
            ),
        )

    try:
        document = Document(
            title=title,
            description=description,
            doc_type=doc_type,
            filename=filename,
            file_size=file_size,
            uploaded_by=current_user["id"],
        )

        if has_supabase_config():
            storage_payload = await asyncio.to_thread(
                _upload_document_to_storage,
                document.id,
                temp_upload_path,
                filename,
                file.content_type or "application/octet-stream",
                doc_type,
            )
            storage_bucket = SUPABASE_STORAGE_BUCKET
        else:
            page_count = 0
            if doc_type == "pdf":
                with fitz.open(temp_upload_path) as local_pdf:
                    page_count = local_pdf.page_count
            storage_payload = {
                "storage_path": temp_upload_path,
                "total_parts": 1,
                "processing_metadata": {
                    "local_source_path": temp_upload_path,
                    "page_count": page_count,
                    "storage_parts": [],
                },
            }
            storage_bucket = "local"

        doc_dict = document.model_dump()
        doc_dict["created_at"] = doc_dict["created_at"].isoformat()
        if doc_dict.get("indexed_at"):
            doc_dict["indexed_at"] = doc_dict["indexed_at"].isoformat()
        doc_dict["storage_bucket"] = storage_bucket
        doc_dict["storage_path"] = storage_payload.get("storage_path")
        doc_dict["total_parts"] = int(storage_payload.get("total_parts") or 1)
        doc_dict["processing_metadata"] = storage_payload.get("processing_metadata") or {}

        await store.create_document(doc_dict)
    finally:
        if has_supabase_config() and os.path.exists(temp_upload_path):
            os.unlink(temp_upload_path)

    return {
        "message": "Document uploaded. Start processing from the Render SSE endpoint.",
        "document_id": document.id,
        "job_id": document.id,
        "status": "uploaded",
        "total_parts": int(doc_dict.get("total_parts") or 1),
        "process_url": f"/api/process/{document.id}",
    }


@api_router.get("/process/{job_id}")
async def process_document_stream(
    job_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Synchronously process a document on Render and stream progress over SSE."""
    current_user = await get_current_user(request, credentials)

    if current_user["role"] not in ["faculty", "admin"]:
        raise HTTPException(status_code=403, detail="Only faculty and admin can process documents")

    document = await store.get_document(job_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    async def event_stream():
        latest_document = await store.get_document(job_id)
        if not latest_document:
            yield _sse_event({"stage": "error", "progress": 100, "error": "Document not found"})
            return

        if latest_document.get("status") == "indexed":
            yield _sse_event(
                {
                    "stage": "ready",
                    "progress": 100,
                    "job_id": job_id,
                    "chunk_count": int(latest_document.get("chunk_count") or 0),
                }
            )
            return

        await store.update_document(job_id, {"status": "processing", "error_message": None})
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(payload: Dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

        emit({"stage": "starting", "progress": 0, "job_id": job_id})

        async def runner() -> None:
            try:
                result = await asyncio.to_thread(
                    _process_pdf_job_sync if latest_document.get("doc_type") == "pdf" else _process_non_pdf_job_sync,
                    latest_document,
                    emit,
                )
                updated_metadata = dict(latest_document.get("processing_metadata") or {})
                updated_metadata["collection_name"] = result.get("collection_name")
                if result.get("page_count") is not None:
                    updated_metadata["page_count"] = result.get("page_count")

                await store.update_document(
                    job_id,
                    {
                        "status": "indexed",
                        "chunk_count": int(result.get("chunks_indexed") or 0),
                        "indexed_at": datetime.now(timezone.utc).isoformat(),
                        "error_message": None,
                        "processing_metadata": updated_metadata,
                    },
                )
                emit(
                    {
                        "stage": "ready",
                        "progress": 100,
                        "job_id": job_id,
                        "chunk_count": int(result.get("chunks_indexed") or 0),
                        "collection_name": result.get("collection_name"),
                    }
                )
            except Exception as exc:
                logger.exception("SSE document processing failed for %s: %s", job_id, exc)
                await store.update_document(
                    job_id,
                    {
                        "status": "failed",
                        "error_message": str(exc),
                    },
                )
                emit(
                    {
                        "stage": "error",
                        "progress": 100,
                        "job_id": job_id,
                        "error": str(exc),
                    }
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "__complete__"})

        runner_task = asyncio.create_task(runner())

        while True:
            payload = await queue.get()
            if payload.get("type") == "__complete__":
                if runner_task.done():
                    break
                continue
            yield _sse_event(payload)

        await runner_task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api_router.post("/documents/url")
async def add_url_document(
    background_tasks: BackgroundTasks,
    request: Request,
    url_request: URLScrapeRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Add a document from URL scraping"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] not in ["faculty", "admin"]:
        raise HTTPException(status_code=403, detail="Only faculty and admin can add documents")

    existing_documents = await store.list_documents(limit=500)
    normalized_url = _normalize_source_url(url_request.url)
    duplicate_document = next(
        (
            doc for doc in existing_documents
            if doc.get("status") != "failed"
            and doc.get("doc_type") == "url"
            and _normalize_source_url(doc.get("filename")) == normalized_url
        ),
        None,
    )
    if duplicate_document:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This URL is already in the knowledge base as \"{duplicate_document.get('title', url_request.url)}\"."
            ),
        )
    
    # Create document record
    document = Document(
        title=url_request.title or url_request.url,
        description=url_request.description,
        doc_type="url",
        filename=url_request.url,
        uploaded_by=current_user["id"]
    )
    
    doc_dict = document.model_dump()
    doc_dict["created_at"] = doc_dict["created_at"].isoformat()
    
    await store.create_document(doc_dict)
    
    # Process URL in background
    async def process_url_background(doc_id: str, url: str, title: str):
        try:
            await store.update_document(doc_id, {"status": "processing"})
            
            result = await DocumentProcessor.process_url(url)
            
            if not result["success"]:
                await store.update_document(
                    doc_id,
                    {"status": "failed", "error_message": result.get("error")},
                )
                return
            
            chunk_count = rag_engine.add_document_chunks(
                document_id=doc_id,
                document_title=title or result.get("title", url),
                chunks=result["chunks"],
                metadata={
                    "doc_type": "url",
                    "source_url": url,
                    "images": result.get("images", []),
                }
            )
            
            await store.update_document(
                doc_id,
                {
                    "status": "indexed",
                    "chunk_count": chunk_count,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}")
            await store.update_document(
                doc_id,
                {"status": "failed", "error_message": str(e)},
            )
    
    background_tasks.add_task(
        process_url_background,
        document.id,
        url_request.url,
        url_request.title
    )
    
    return {
        "message": "URL queued for scraping and indexing",
        "document_id": document.id,
        "status": "pending"
    }


@api_router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """List all documents"""
    await get_current_user(request, credentials)
    
    documents = await store.list_documents(limit=100)
    
    return [
        DocumentResponse(
            id=doc["id"],
            title=doc["title"],
            description=doc.get("description"),
            doc_type=doc["doc_type"],
            filename=doc["filename"],
            file_size=doc.get("file_size", 0),
            chunk_count=doc.get("chunk_count", 0),
            status=doc["status"],
            uploaded_by=doc.get("uploaded_by"),
            created_at=doc["created_at"],
            indexed_at=doc.get("indexed_at"),
            error_message=doc.get("error_message"),
            total_parts=int(doc.get("total_parts") or 1),
            processing_metadata=doc.get("processing_metadata") or {},
        )
        for doc in documents
    ]


@api_router.get("/documents/{document_id}/chunks", response_model=DocumentChunkPreviewResponse)
async def preview_document_chunks(
    document_id: str,
    limit: int = 8,
    request: Request = None,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Preview extracted chunks for a document."""
    current_user = await get_current_user(request, credentials)

    if current_user["role"] not in ["faculty", "admin"]:
        raise HTTPException(status_code=403, detail="Only faculty and admin can preview document chunks")

    document = await store.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = rag_engine.get_document_chunks_preview(document_id, limit=limit)
    if not chunks and document.get("doc_type") == "pdf":
        chunks = preview_large_pdf_chunks(_document_collection_name(document), document_id, limit=limit)
    return DocumentChunkPreviewResponse(
        document_id=document["id"],
        title=document["title"],
        status=document["status"],
        chunk_count=document.get("chunk_count", 0),
        chunks=[
            DocumentChunkPreview(
                chunk_index=chunk.get("chunk_index", 0),
                chunk_text=chunk.get("chunk_text", ""),
                metadata=chunk.get("metadata") or {},
            )
            for chunk in chunks
        ],
    )


@api_router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Delete a document (admin only)"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete documents")
    
    document = await store.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Delete from RAG engine
    rag_engine.delete_document(document_id)
    delete_large_pdf_document(_document_collection_name(document), document_id)
    
    # Delete from database
    await store.delete_document(document_id)
    
    return {"message": "Document deleted successfully"}


@api_router.post("/documents/bulk-delete", response_model=DocumentBulkDeleteResponse)
async def bulk_delete_documents(
    payload: DocumentBulkDeleteRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Delete multiple documents at once (admin only)."""
    current_user = await get_current_user(request, credentials)

    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete documents")

    unique_ids = list(dict.fromkeys(doc_id for doc_id in payload.document_ids if doc_id))
    if not unique_ids:
        raise HTTPException(status_code=400, detail="No document IDs were provided")

    deleted_count = 0
    not_found_ids: List[str] = []

    for document_id in unique_ids:
        document = await store.get_document(document_id)
        if not document:
            not_found_ids.append(document_id)
            continue

        rag_engine.delete_document(document_id)
        delete_large_pdf_document(_document_collection_name(document), document_id)
        await store.delete_document(document_id)
        deleted_count += 1

    return DocumentBulkDeleteResponse(
        deleted_count=deleted_count,
        not_found_ids=not_found_ids,
    )


# ==================== Analytics Routes ====================

@api_router.get("/analytics/overview", response_model=AnalyticsOverview)
async def get_analytics_overview(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get analytics overview"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] not in ["faculty", "admin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    all_logs = await store.list_query_logs()
    today_logs = await store.list_query_logs(start_iso=today_start.isoformat())
    total_queries = len(all_logs)
    total_documents = await store.count_documents()
    total_users = await store.count_users()
    queries_today = len(today_logs)
    avg_response_time = (
        sum(log.get("processing_time_ms", 0) for log in all_logs) / total_queries
        if total_queries
        else 0
    )
    voice_queries = sum(1 for log in all_logs if log.get("voice_input"))
    voice_percentage = (voice_queries / total_queries * 100) if total_queries > 0 else 0
    
    return AnalyticsOverview(
        total_queries=total_queries,
        total_documents=total_documents,
        total_users=total_users,
        queries_today=queries_today,
        avg_response_time_ms=avg_response_time or 0,
        voice_query_percentage=voice_percentage
    )


@api_router.get("/analytics/daily")
async def get_daily_analytics(
    days: int = 7,
    request: Request = None,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get daily analytics for the past N days"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] not in ["faculty", "admin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    stats = []
    
    for i in range(days):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        date_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = date_start + timedelta(days=1)
        logs = await store.list_query_logs(start_iso=date_start.isoformat(), end_iso=date_end.isoformat())
        query_count = len(logs)
        unique_users = len({log.get("user_id") for log in logs if log.get("user_id")})
        avg_time = (
            sum(log.get("processing_time_ms", 0) for log in logs) / query_count
            if query_count
            else 0
        )
        
        stats.append({
            "date": date_start.strftime("%Y-%m-%d"),
            "query_count": query_count,
            "unique_users": unique_users,
            "avg_response_time": avg_time or 0
        })
    
    return {"stats": stats[::-1]}  # Reverse to show oldest first


# ==================== Admin Routes ====================

@api_router.get("/admin/users")
async def list_users(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """List all users (admin only)"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    users = await store.list_users(limit=100)
    return {"users": users}


@api_router.patch("/admin/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Update a user's role (admin only)"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if role not in ["student", "faculty", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    updated = await store.update_user_role(user_id, role)
    
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": f"User role updated to {role}"}


@api_router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Delete a user (admin only)"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    deleted = await store.delete_user(user_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": "User deleted successfully"}


# ==================== Health Check ====================

@api_router.get("/")
async def root():
    """API health check"""
    return {
        "message": "SET Academic Chatbot API",
        "status": "healthy",
        "version": "1.0.0"
    }


@api_router.get("/health")
async def health_check():
    """Detailed health check"""
    # Check database connection
    db_status = "connected"
    try:
        await store.ping()
    except Exception as e:
        db_status = f"disconnected: {str(e)}"

    rag_stats = rag_engine.get_stats()

    return {
        "status": "healthy",
        "database": db_status,
        "database_provider": store.backend_name(),
        "auth_provider": "supabase",
        "supabase": {
            "configured": has_supabase_config(),
            "url": SUPABASE_URL or None,
            "storage_bucket": SUPABASE_STORAGE_BUCKET,
        },
        "rag_engine": {
            "status": "active",
            "indexed_chunks": rag_stats["total_chunks"],
            "vector_backend": rag_stats.get("vector_backend", "unknown"),
            "vector_store_mode": rag_stats.get("vector_store_mode", "unknown"),
            "chat_provider": rag_stats.get("chat_provider", "unknown"),
            "remote_llm_available": rag_stats.get("remote_llm_available", False),
            "ollama_available": rag_stats.get("ollama_available", False),
            "chat_model": rag_stats.get("chat_model", "unknown"),
            "embedding_provider": rag_stats.get("embedding_provider", "unknown"),
            "embedding_model": rag_stats.get("embedding_model", "unknown"),
            "web_fallback_enabled": ENABLE_WEB_FALLBACK,
            "gemini_events": KRMUEventsFeed.gemini_status(),
        }
    }


# ==================== Knowledge Base Seed Routes ====================

@api_router.post("/admin/seed-knowledge-base")
async def seed_knowledge_base(
    background_tasks: BackgroundTasks,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Seed the knowledge base with SET institutional documents (admin only)"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from knowledge_seeder import KnowledgeBaseSeeder
    seeder = KnowledgeBaseSeeder(store, rag_engine)
    
    # Run seeding in background
    async def run_seeding():
        try:
            result = await seeder.seed_all()
            logger.info(f"Knowledge base seeding completed: {result}")
        except Exception as e:
            logger.error(f"Knowledge base seeding error: {e}")
    
    background_tasks.add_task(run_seeding)
    
    return {
        "message": "Knowledge base seeding started",
        "status": "processing"
    }


@api_router.get("/admin/seed-status")
async def get_seed_status(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Get knowledge base seed status (admin only)"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    seed_count = await store.count_documents({"is_seed": True})
    total_count = await store.count_documents({})
    categories = await store.get_seed_categories()
    
    return {
        "seeded_documents": seed_count,
        "total_documents": total_count,
        "categories": categories,
        "rag_stats": rag_engine.get_stats()
    }


@api_router.delete("/admin/clear-seeds")
async def clear_seed_documents(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Clear all seeded documents (admin only)"""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from knowledge_seeder import KnowledgeBaseSeeder
    seeder = KnowledgeBaseSeeder(store, rag_engine)
    result = await seeder.clear_seeds()
    
    return result


@api_router.post("/admin/retrieval-evaluate", response_model=RetrievalEvaluationResponse)
async def evaluate_retrieval(
    payload: RetrievalEvaluationRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Inspect retrieval results for a database-mode question (admin only)."""
    current_user = await get_current_user(request, credentials)

    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    result = rag_engine.evaluate_retrieval(payload.query, top_k=payload.top_k)
    return RetrievalEvaluationResponse(
        query=result["query"],
        vector_backend=result["vector_backend"],
        embedding_provider=result["embedding_provider"],
        embedding_model=result["embedding_model"],
        chunk_count=result["chunk_count"],
        results=[
            DocumentChunkPreview(
                chunk_index=item.get("chunk_index", 0),
                chunk_text=item.get("chunk_text", ""),
                relevance_score=item.get("relevance_score", 0),
                metadata=item.get("metadata") or {},
            )
            for item in result["results"]
        ],
    )


@api_router.post("/admin/refresh-ollama")
@api_router.post("/admin/refresh-models")
async def refresh_ollama_connection(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Refresh remote and local model connections (admin only)."""
    current_user = await get_current_user(request, credentials)
    
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    status = rag_engine.refresh_model_connections()
    rag_stats = rag_engine.get_stats()
    chat_provider = rag_stats.get("chat_provider", "fallback")
    chat_model = rag_stats.get("chat_model", "unknown")

    if status["remote_llm_available"]:
        message = f"Remote LLM connection active ({chat_model})"
    elif status["ollama_available"]:
        message = f"Ollama fallback active ({chat_model})"
    else:
        message = "No remote LLM or Ollama backend is currently available"
    
    return {
        "ollama_available": status["ollama_available"],
        "remote_llm_available": status["remote_llm_available"],
        "remote_embeddings_available": status.get("remote_embeddings_available", False),
        "chat_provider": chat_provider,
        "chat_model": chat_model,
        "message": message,
    }


# Include the router in the main app
app.include_router(api_router)

_cors_origins = _parse_cors_origins(os.environ.get("CORS_ORIGINS", ""))
_cors_origin_regex = _resolve_cors_origin_regex(_cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins or ["http://localhost:3000"],
    allow_origin_regex=_cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Validate configuration and connections on startup"""
    from auth import CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY, CLERK_ISSUER

    logger.info("Starting SET Academic Chatbot API...")

    # Validate Clerk configuration
    if not CLERK_PUBLISHABLE_KEY:
        logger.warning("CLERK_PUBLISHABLE_KEY not set - Clerk authentication will not work")
    elif not CLERK_SECRET_KEY:
        logger.warning("CLERK_SECRET_KEY not set - Clerk user fetching will not work")
    elif not CLERK_ISSUER:
        logger.warning("Could not decode Clerk issuer from publishable key - JWT verification may fail")
    else:
        logger.info(f"Clerk configured with issuer: {CLERK_ISSUER}")

    # Validate database connection
    try:
        await store.ping()
        logger.info("%s connection: OK", store.backend_name().capitalize())
    except Exception as e:
        logger.error("%s connection failed: %s", store.backend_name().capitalize(), e)

    if has_supabase_config():
        logger.info("Supabase configured for project: %s", SUPABASE_URL)
    logger.info("CORS origins: %s", _cors_origins or ["http://localhost:3000"])
    logger.info("CORS origin regex: %s", _cors_origin_regex or "disabled")

    # Log model provider status
    rag_stats = rag_engine.get_stats()
    if rag_stats.get("remote_llm_available"):
        logger.info("Remote vLLM available with model: %s", rag_stats.get("chat_model"))
    elif rag_stats.get("ollama_available"):
        logger.info("Using local Ollama fallback with model: %s", OLLAMA_CHAT_MODEL)
    else:
        logger.warning("No remote vLLM or local Ollama backend is currently available")

    logger.info("Startup complete")


@app.on_event("shutdown")
async def shutdown_db_client():
    if client:
        client.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
