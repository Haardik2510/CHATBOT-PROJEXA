import traceback
import sys

print("Python:", sys.version)
print()

# Test each import individually
modules = [
    ("models", "from models import UserCreate, UserLogin, UserResponse, TokenResponse, User, Document, DocumentResponse, ChatRequest, ChatResponse, SourceCitation, ChatSession, QueryLog, AnalyticsOverview, DailyStats, URLScrapeRequest"),
    ("auth", "from auth import hash_password, verify_password, create_access_token, decode_token, require_role, verify_clerk_session_token, fetch_clerk_user"),
    ("document_processor", "from document_processor import DocumentProcessor"),
    ("rag_engine", "from rag_engine import rag_engine"),
    ("web_search", "from web_search import get_web_search_fallback"),
]

for name, imp in modules:
    try:
        exec(imp)
        print(f"OK: {name}")
    except Exception as e:
        print(f"FAIL: {name}")
        traceback.print_exc()
        print()

print("\n--- Now trying full server import ---")
try:
    import server
    print("OK: server imported successfully")
except Exception as e:
    print(f"FAIL: server import")
    traceback.print_exc()
