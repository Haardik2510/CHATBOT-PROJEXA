"""Authentication module with JWT and role-based access"""
import os
import base64
import hashlib
import hmac
import secrets
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
import jwt
import httpx
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

# Configuration
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "set-academic-chatbot-secret-key-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY")
CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()
PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 390000


def _decode_clerk_publishable_key(publishable_key: str) -> Optional[str]:
    """Extract the Clerk instance domain from a publishable key."""
    try:
        encoded = publishable_key.split("_", 2)[2]
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.b64decode(encoded + padding).decode()
        return decoded.rstrip("$")
    except Exception:
        return None


CLERK_DOMAIN = _decode_clerk_publishable_key(CLERK_PUBLISHABLE_KEY) if CLERK_PUBLISHABLE_KEY else None
CLERK_ISSUER = f"https://{CLERK_DOMAIN}" if CLERK_DOMAIN else None
CLERK_API_URL = "https://api.clerk.com/v1"
CLERK_JWKS_CLIENT = jwt.PyJWKClient(f"{CLERK_ISSUER}/.well-known/jwks.json") if CLERK_ISSUER else None


def hash_password(password: str) -> str:
    """Hash a password for storage"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    if not hashed_password:
        return False

    if hashed_password.startswith(f"{PBKDF2_PREFIX}$"):
        try:
            _, iterations, salt, expected = hashed_password.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                salt.encode("utf-8"),
                int(iterations),
            )
            return hmac.compare_digest(digest.hex(), expected)
        except (ValueError, TypeError):
            return False

    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def verify_clerk_session_token(token: str) -> Optional[dict]:
    """Verify a Clerk session token and return its claims."""
    if not CLERK_JWKS_CLIENT or not CLERK_ISSUER:
        logger.warning("Clerk JWKS client or issuer not configured. Check CLERK_PUBLISHABLE_KEY.")
        return None

    try:
        signing_key = CLERK_JWKS_CLIENT.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            options={"verify_aud": False},
        )
        # Verify the token hasn't expired
        exp = payload.get("exp")
        if exp and exp < datetime.now(timezone.utc).timestamp():
            logger.warning("Clerk token has expired")
            return None
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Clerk token signature has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid Clerk token: {e}")
        return None
    except Exception as e:
        logger.warning(f"Clerk token verification failed: {e}")
        return None


async def fetch_clerk_user(clerk_user_id: str) -> Optional[dict]:
    """Fetch a Clerk user via Clerk's Backend API."""
    if not CLERK_SECRET_KEY:
        return None

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{CLERK_API_URL}/users/{clerk_user_id}",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
            timeout=10.0,
        )

    if response.status_code != 200:
        return None

    return response.json()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncIOMotorDatabase = None
) -> dict:
    """Get the current authenticated user from the token"""
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    
    return {
        "id": user_id,
        "email": payload.get("email"),
        "name": payload.get("name"),
        "role": payload.get("role", "student")
    }


def require_role(allowed_roles: list):
    """Dependency to require specific roles for access"""
    async def role_checker(
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> dict:
        token = credentials.credentials
        payload = decode_token(token)
        
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        
        user_role = payload.get("role", "student")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {allowed_roles}",
            )
        
        return {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "name": payload.get("name"),
            "role": user_role
        }
    
    return role_checker
