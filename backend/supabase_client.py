"""Shared Supabase helpers for auth, storage, and database migration."""
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - keeps partial setups import-safe
    Client = Any  # type: ignore[assignment]
    create_client = None


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


def _strip_broken_local_proxies() -> None:
    """Remove invalid loopback proxy settings that block outbound Supabase requests."""
    blocked_values = {
        "http://127.0.0.1:9",
        "https://127.0.0.1:9",
        "http://localhost:9",
        "https://localhost:9",
    }

    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        value = (os.environ.get(key) or "").strip().lower()
        if value in blocked_values:
            os.environ.pop(key, None)


_strip_broken_local_proxies()


def _normalize_supabase_url(url: str, project_ref: str) -> str:
    """Support either a full Supabase URL or just a project ref."""
    normalized = (url or "").strip().rstrip("/")
    if normalized:
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized
        return f"https://{normalized}.supabase.co"

    ref = (project_ref or "").strip()
    if ref:
        return f"https://{ref}.supabase.co"

    return ""


SUPABASE_PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "").strip()
SUPABASE_URL = _normalize_supabase_url(
    os.environ.get("SUPABASE_URL", ""),
    SUPABASE_PROJECT_REF,
)
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "documents").strip()
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


@lru_cache(maxsize=1)
def get_supabase_admin_client() -> Optional[Client]:
    """Return a cached Supabase admin client when configured."""
    if not SUPABASE_ENABLED or create_client is None:
        return None
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


@lru_cache(maxsize=1)
def get_supabase_public_client() -> Optional[Client]:
    """Return a cached Supabase public client for end-user auth flows."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY or create_client is None:
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def has_supabase_config() -> bool:
    """Return whether Supabase admin integration is configured."""
    return bool(get_supabase_admin_client())


async def fetch_supabase_user(access_token: str) -> Optional[Dict[str, Any]]:
    """Validate and fetch the current Supabase auth user via the Auth REST API."""
    if not access_token or not SUPABASE_URL:
        return None

    api_key = SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY
    if not api_key:
        return None

    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {access_token}",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{SUPABASE_URL}/auth/v1/user", headers=headers)

    if response.status_code != 200:
        return None

    return response.json()


def upload_bytes(
    path: str,
    content: bytes,
    content_type: str,
    bucket_name: Optional[str] = None,
) -> Optional[str]:
    """Upload bytes to the configured Supabase Storage bucket."""
    client = get_supabase_admin_client()
    if not client:
        return None

    bucket = client.storage.from_(bucket_name or SUPABASE_STORAGE_BUCKET)
    bucket.upload(
        path=path,
        file=content,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return path


def download_bytes(
    path: str,
    bucket_name: Optional[str] = None,
) -> Optional[bytes]:
    """Download bytes from the configured Supabase Storage bucket."""
    client = get_supabase_admin_client()
    if not client or not path:
        return None

    bucket = client.storage.from_(bucket_name or SUPABASE_STORAGE_BUCKET)
    return bucket.download(path)
