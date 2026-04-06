"""Main FastAPI application for SET Academic Chatbot"""
import json
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
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
import time
import uuid

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from models import (
    UserCreate, UserLogin, UserResponse, TokenResponse, User,
    Document, DocumentResponse, ChatRequest, ChatResponse, SourceCitation,
    ChatSession, QueryLog, AnalyticsOverview, DailyStats, URLScrapeRequest
)
from auth import (
    hash_password, verify_password, create_access_token, 
    decode_token, require_role, verify_clerk_session_token, fetch_clerk_user
)
from document_processor import DocumentProcessor
from rag_engine import rag_engine, OLLAMA_CHAT_MODEL
from web_search import WebSearchFallback, get_web_search_fallback
from app_store import AppStore, utc_now_iso
from supabase_client import (
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
    SUPABASE_STORAGE_BUCKET,
    fetch_supabase_user,
    get_supabase_admin_client,
    get_supabase_public_client,
    has_supabase_config,
    upload_bytes,
)

ENABLE_WEB_FALLBACK = os.environ.get("ENABLE_WEB_FALLBACK", "false").strip().lower() == "true"

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
        "sources": []
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

    return {
        "response": rag_engine.generate_web_response(
            message,
            search_results,
            conversation_history=conversation_history,
        ),
        "sources": WebSearchFallback.build_sources(search_results),
    }, True


async def _resolve_chat_result(
    message: str,
    answer_mode: str = "database",
    conversation_history: Optional[List[Dict]] = None,
) -> tuple[dict, bool]:
    """Resolve a non-streaming chat result for the selected source mode."""
    normalized_mode = _normalize_answer_mode(answer_mode)

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
            }, True

    is_web_fallback = False
    rag_result = _default_chat_result()

    try:
        rag_result = rag_engine.chat(message, conversation_history=conversation_history)

        if not _has_good_sources(rag_result.get("sources", [])):
            rag_result = {
                "response": (
                    "I couldn't find a sufficiently grounded answer in the indexed knowledge base. "
                    "Please rephrase the question, switch to Internet mode, or upload/seed more relevant documents."
                ),
                "sources": rag_result.get("sources", []),
            }
    except Exception as exc:
        logger.exception("Chat pipeline failed for message %s: %s", message, exc)
        rag_result = {
            "response": (
                "I ran into a temporary issue while checking the indexed knowledge base. "
                "Please try again in a moment."
            ),
            "sources": [],
        }

    return rag_result, is_web_fallback


def _sse_event(payload: dict) -> str:
    """Format a Server-Sent Event payload."""
    return f"data: {json.dumps(payload)}\n\n"


# ==================== Auth Routes ====================

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
        session_id=session_id,
        voice_output=chat_request.voice_input,
        answer_mode=answer_mode,
    )


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

        async def internet_stream():
            yield _sse_event(
                {
                    "type": "meta",
                    "session_id": session_id,
                    "sources": rag_result.get("sources", []),
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

        async def fallback_stream():
            yield _sse_event(
                {
                    "type": "meta",
                    "session_id": session_id,
                    "sources": rag_result.get("sources", []),
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

    async def event_stream():
        response_parts = []

        yield _sse_event(
            {
                "type": "meta",
                "session_id": session_id,
                "sources": source_payload,
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

async def process_document_background(document_id: str, file_content: bytes, file_type: str, title: str):
    """Background task to process and index a document"""
    try:
        # Update status to processing
        await store.update_document(document_id, {"status": "processing"})
        
        # Process the document
        result = await asyncio.wait_for(
            asyncio.to_thread(DocumentProcessor.process_file, file_content, file_type),
            timeout=300
        )
        
        if not result["success"]:
            await store.update_document(
                document_id,
                {"status": "failed", "error_message": result.get("error", "Unknown error")},
            )
            return
        
        # Add to RAG engine
        chunk_count = await asyncio.wait_for(
            asyncio.to_thread(
                rag_engine.add_document_chunks,
                document_id=document_id,
                document_title=title,
                chunks=result["chunks"],
                metadata={"doc_type": file_type}
            ),
            timeout=300
        )
        
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
                    "Document processing timed out. Try a smaller file, a text-based PDF, "
                    "or split this document into parts."
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
    background_tasks: BackgroundTasks,
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
    
    # Read file content
    file_content = await file.read()
    file_size = len(file_content)

    # Create document record
    document = Document(
        title=title,
        description=description,
        doc_type=doc_type,
        filename=filename,
        file_size=file_size,
        uploaded_by=current_user["id"]
    )

    storage_path = None
    if has_supabase_config():
        sanitized_name = filename.replace("\\", "_").replace("/", "_")
        storage_path = f"{document.id}/{sanitized_name}"
        upload_result = await asyncio.to_thread(
            upload_bytes,
            storage_path,
            file_content,
            file.content_type or "application/octet-stream",
            SUPABASE_STORAGE_BUCKET,
        )
        if not upload_result:
            raise HTTPException(status_code=500, detail="Failed to upload file to Supabase Storage")
    
    doc_dict = document.model_dump()
    doc_dict["created_at"] = doc_dict["created_at"].isoformat()
    if doc_dict.get("indexed_at"):
        doc_dict["indexed_at"] = doc_dict["indexed_at"].isoformat()
    if storage_path:
        doc_dict["storage_bucket"] = SUPABASE_STORAGE_BUCKET
        doc_dict["storage_path"] = storage_path
    
    await store.create_document(doc_dict)
    
    # Process in background
    background_tasks.add_task(
        process_document_background,
        document.id,
        file_content,
        doc_type,
        title
    )
    
    return {
        "message": "Document uploaded and queued for processing",
        "document_id": document.id,
        "status": "pending"
    }


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
                metadata={"doc_type": "url", "source_url": url}
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
            error_message=doc.get("error_message")
        )
        for doc in documents
    ]


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
    
    # Delete from database
    await store.delete_document(document_id)
    
    return {"message": "Document deleted successfully"}


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
            "embedding_model": rag_stats.get("embedding_model", "unknown"),
            "web_fallback_enabled": ENABLE_WEB_FALLBACK,
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
