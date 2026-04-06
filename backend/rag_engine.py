"""RAG Engine using Supabase pgvector or ChromaDB with OpenAI-compatible and Ollama chat backends."""
import json
import os
import logging
import hashlib
import re
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
from chromadb.errors import InvalidArgumentError
import httpx
from supabase_client import get_supabase_admin_client, has_supabase_config

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


def _resolve_chroma_path() -> str:
    """Resolve a writable Chroma storage path for local development."""
    configured_path = os.environ.get("CHROMA_PATH")
    if configured_path:
        return str(Path(configured_path).expanduser())

    return str(ROOT_DIR / "chroma_db")


def _normalize_openai_base_url(base_url: str) -> str:
    """Normalize an OpenAI-compatible base URL to include the /v1 suffix."""
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return ""
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


DEFAULT_CHROMA_PATH = _resolve_chroma_path()

# Primary chat provider configuration (vLLM / OpenAI-compatible)
LLM_BASE_URL = _normalize_openai_base_url(os.environ.get("LLM_BASE_URL", ""))
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct").strip()
LLM_REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "180"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "384"))
EMBEDDING_BASE_URL = _normalize_openai_base_url(os.environ.get("EMBEDDING_BASE_URL", ""))
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", LLM_API_KEY).strip()
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "").strip()

# Local fallback / embeddings configuration
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3").strip()
OLLAMA_EMBEDDING_MODEL = os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text").strip()


class OpenAICompatibleClient:
    """Client for a remote OpenAI-compatible endpoint such as vLLM."""

    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        model: str = LLM_MODEL,
        api_key: str = LLM_API_KEY,
    ):
        self.base_url = _normalize_openai_base_url(base_url)
        self.model = model
        self.api_key = api_key
        self.is_available = False
        self._check_availability()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _check_availability(self):
        """Check whether the remote OpenAI-compatible endpoint is reachable."""
        if not self.base_url:
            self.is_available = False
            logger.info("No remote LLM base URL configured; local Ollama fallback will be used")
            return

        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=10.0,
            )
            if response.status_code == 200:
                self.is_available = True
                models = response.json().get("data", [])
                model_ids = [model.get("id", "unknown") for model in models]
                logger.info(
                    "Remote LLM endpoint available at %s with models: %s",
                    self.base_url,
                    ", ".join(model_ids) if model_ids else "none reported",
                )
            else:
                self.is_available = False
                logger.warning(
                    "Remote LLM endpoint returned %s from /models",
                    response.status_code,
                )
        except Exception as exc:
            self.is_available = False
            logger.warning("Remote LLM connection failed: %s", exc)

    def list_models(self) -> List[str]:
        """List available models exposed by the remote endpoint."""
        if not self.is_available:
            return []

        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=10.0,
            )
            if response.status_code == 200:
                return [item.get("id", "unknown") for item in response.json().get("data", [])]
        except Exception:
            pass
        return []


class OpenAICompatibleEmbeddingClient:
    """Optional OpenAI-compatible embeddings client."""

    def __init__(
        self,
        base_url: str = EMBEDDING_BASE_URL,
        model: str = EMBEDDING_MODEL,
        api_key: str = EMBEDDING_API_KEY,
    ):
        self.base_url = _normalize_openai_base_url(base_url)
        self.model = model
        self.api_key = api_key
        self.is_available = False
        self._check_availability()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _check_availability(self):
        """Check whether a remote embeddings endpoint is configured and reachable."""
        if not self.base_url or not self.model:
            self.is_available = False
            return

        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=10.0,
            )
            self.is_available = response.status_code == 200
            if self.is_available:
                logger.info(
                    "Remote embedding endpoint available at %s using model %s",
                    self.base_url,
                    self.model,
                )
            else:
                logger.warning(
                    "Remote embedding endpoint returned %s from /models",
                    response.status_code,
                )
        except Exception as exc:
            self.is_available = False
            logger.warning("Remote embedding connection failed: %s", exc)

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embeddings with a remote OpenAI-compatible endpoint."""
        if not self.is_available:
            raise RuntimeError("Remote embeddings endpoint is not available")

        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers=self._headers(),
            json={
                "model": self.model,
                "input": text,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or []
        if not data or not data[0].get("embedding"):
            raise RuntimeError("Remote embeddings endpoint returned no embedding payload")
        return data[0]["embedding"]

    def chat(self, messages: List[Dict], model: Optional[str] = None, temperature: float = 0.7) -> str:
        """Generate a non-streaming chat completion from the remote endpoint."""
        if not self.is_available:
            raise RuntimeError("Remote OpenAI-compatible endpoint is not available")

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": model or self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
                "max_tokens": LLM_MAX_TOKENS,
            },
            timeout=LLM_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        return (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )

    async def stream_chat(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream chat completion chunks from the remote endpoint."""
        if not self.is_available:
            raise RuntimeError("Remote OpenAI-compatible endpoint is not available")

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": model or self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                    "max_tokens": LLM_MAX_TOKENS,
                },
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data = line[6:].strip()
                    if data == "[DONE]":
                        break

                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    delta = (
                        payload.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if delta:
                        yield delta


class OllamaClient:
    """Client for Ollama API interactions."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.is_available = False
        self._check_availability()

    @staticmethod
    def _matches_model(requested_model: str, available_model: str) -> bool:
        requested = (requested_model or "").strip()
        available = (available_model or "").strip()
        if not requested or not available:
            return False
        return requested == available or available.split(":", 1)[0] == requested

    def _check_availability(self):
        """Check if Ollama is available and log available models."""
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                self.is_available = True
                models = response.json().get("models", [])
                model_names = [m.get("name", "unknown") for m in models]
                logger.info(
                    "Ollama available with %s models: %s",
                    len(models),
                    ", ".join(model_names),
                )

                if any(self._matches_model(OLLAMA_CHAT_MODEL, name) for name in model_names):
                    logger.info("Preferred Ollama chat model '%s' is available", OLLAMA_CHAT_MODEL)
                else:
                    logger.warning(
                        "Preferred Ollama chat model '%s' not found. Available: %s",
                        OLLAMA_CHAT_MODEL,
                        model_names,
                    )
            else:
                self.is_available = False
                logger.warning("Ollama not available - local fallback disabled")
        except Exception as exc:
            self.is_available = False
            logger.warning("Ollama connection failed: %s", exc)

    def list_models(self) -> List[str]:
        """List available Ollama models."""
        if not self.is_available:
            return []

        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return [m.get("name", "unknown") for m in models]
        except Exception:
            pass
        return []

    def generate_embedding(self, text: str, model: Optional[str] = None) -> List[float]:
        """Generate embeddings with Ollama or fall back to a local hash embedding."""
        if not self.is_available:
            return self._fallback_embedding(text)

        try:
            response = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": model or OLLAMA_EMBEDDING_MODEL, "input": text},
                timeout=60.0,
            )
            if response.status_code == 200:
                payload = response.json()
                if "embedding" in payload:
                    return payload["embedding"]
                if payload.get("embeddings"):
                    return payload["embeddings"][0]
            logger.warning("Ollama embedding failed: %s", response.status_code)
        except Exception as exc:
            logger.warning("Ollama embedding error: %s", exc)

        return self._fallback_embedding(text)

    def _fallback_embedding(self, text: str, dimension: int = 768) -> List[float]:
        """Generate a deterministic fallback embedding when no embedding model is reachable."""
        import numpy as np

        text_hash = hashlib.md5(text.encode()).hexdigest()
        seed = int(text_hash[:8], 16)
        np.random.seed(seed)
        embedding = np.random.randn(dimension).astype(float)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding.tolist()

    def chat(self, messages: List[Dict], model: Optional[str] = None, temperature: float = 0.7) -> str:
        """Generate a non-streaming chat response with Ollama."""
        if not self.is_available:
            raise RuntimeError("Ollama is not available for chat generation")

        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model or OLLAMA_CHAT_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": LLM_MAX_TOKENS,
                    },
                },
                timeout=LLM_REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                payload = response.json()
                return payload.get("message", {}).get("content", "")
            logger.warning("Ollama chat failed: %s", response.status_code)
        except Exception as exc:
            logger.warning("Ollama chat error: %s", exc)

        raise RuntimeError("Ollama chat generation failed")

    async def stream_chat(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream chat chunks from Ollama."""
        if not self.is_available:
            raise RuntimeError("Ollama is not available for streaming chat")

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json={
                        "model": model or OLLAMA_CHAT_MODEL,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "temperature": temperature,
                            "num_predict": LLM_MAX_TOKENS,
                        },
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        chunk = payload.get("message", {}).get("content", "")
                        if chunk:
                            yield chunk
        except Exception as exc:
            logger.warning("Ollama streaming chat error: %s", exc)
            raise RuntimeError("Ollama streaming chat failed") from exc


class RAGEngine:
    """RAG Engine for document retrieval and response generation."""

    def __init__(self):
        self.remote_llm = OpenAICompatibleClient()
        self.remote_embeddings = OpenAICompatibleEmbeddingClient()
        self.ollama = OllamaClient()
        self.supabase = get_supabase_admin_client() if has_supabase_config() else None
        self.use_supabase_vectors = bool(self.supabase)
        self.supabase_embedding_dimension = 768
        self.last_vector_backend_used = "supabase" if self.use_supabase_vectors else "chroma"

        self.storage_path = DEFAULT_CHROMA_PATH
        self.chroma_client = self._create_chroma_client()
        self.collection_name = (
            f"academic_documents_{self.supabase_embedding_dimension}"
            if self.use_supabase_vectors
            else "academic_documents"
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self.chroma_embedding_dimension = self._detect_collection_dimension()
        self.embedding_dimension = (
            self.supabase_embedding_dimension
            if self.use_supabase_vectors
            else self.chroma_embedding_dimension
        )

        logger.info(
            "RAG Engine initialized with %s documents at %s",
            self._count_chunks(),
            self.storage_path,
        )
        logger.info("Remote LLM available: %s", self.remote_llm.is_available)
        logger.info("Ollama available: %s", self.ollama.is_available)
        logger.info("Supabase vector store enabled: %s", self.use_supabase_vectors)
        if self.embedding_dimension:
            logger.info("Detected collection embedding dimension: %s", self.embedding_dimension)

    def _has_semantic_embeddings(self) -> bool:
        """Return whether a real embedding provider is available."""
        return self.remote_embeddings.is_available or self.ollama.is_available

    def _embedding_provider_name(self) -> str:
        """Return the active embedding provider label."""
        if self.remote_embeddings.is_available:
            return "remote"
        if self.ollama.is_available:
            return "ollama"
        return "hash-based"

    def _embedding_model_name(self) -> str:
        """Return the active embedding model label."""
        if self.remote_embeddings.is_available:
            return self.remote_embeddings.model or "remote-embedding-model"
        if self.ollama.is_available:
            return OLLAMA_EMBEDDING_MODEL
        return "hash-based"

    def _generate_embedding(self, text: str) -> List[float]:
        """Generate embeddings with the best available provider without changing default behavior."""
        if self.remote_embeddings.is_available:
            try:
                return self.remote_embeddings.generate_embedding(text)
            except Exception as exc:
                logger.warning("Remote embedding generation failed, falling back: %s", exc)

        if self.ollama.is_available:
            return self.ollama.generate_embedding(text)

        return self.ollama._fallback_embedding(text)

    def _create_chroma_client(self):
        """Create a Chroma client and fall back to a fresh writable store if needed."""
        candidate_paths = [Path(self.storage_path), ROOT_DIR / "chroma_db_runtime"]

        for candidate in candidate_paths:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(
                    path=str(candidate),
                    settings=Settings(anonymized_telemetry=False),
                )
                self.storage_path = str(candidate)
                return client
            except Exception as exc:
                logger.warning("Failed to initialize Chroma at %s: %s", candidate, exc)

        raise RuntimeError("Unable to initialize a writable Chroma database")

    @staticmethod
    def _extract_query_terms(query: str, max_terms: int = 8) -> List[str]:
        """Extract meaningful lowercase query terms for lexical retrieval."""
        stopwords = {
            "the", "and", "for", "with", "that", "this", "from", "what", "when",
            "where", "which", "about", "into", "your", "have", "will", "would",
            "could", "should", "tell", "please", "there", "their", "them", "just",
            "does", "did", "are", "can", "how", "why", "who",
        }
        terms = []
        for term in re.findall(r"[a-z0-9]+", (query or "").lower()):
            if len(term) < 2 or term in stopwords or term in terms:
                continue
            terms.append(term)
            if len(terms) >= max_terms:
                break
        return terms

    @classmethod
    def _score_lexical_match(cls, query: str, chunk_text: str, document_title: str = "") -> float:
        """Score lexical similarity between the query and a chunk/title."""
        haystack = f"{document_title} {chunk_text}".lower()
        query_text = (query or "").strip().lower()
        if not haystack.strip() or not query_text:
            return 0.0

        query_terms = cls._extract_query_terms(query_text)
        if not query_terms:
            return 0.0

        score = 0.0
        if query_text in haystack:
            score += 0.35

        match_count = sum(1 for term in query_terms if term in haystack)
        coverage_ratio = match_count / len(query_terms)
        score += 0.50 * coverage_ratio

        if len(query_terms) > 1:
            bigrams = [
                f"{query_terms[index]} {query_terms[index + 1]}"
                for index in range(len(query_terms) - 1)
            ]
            bigram_matches = sum(1 for phrase in bigrams if phrase in haystack)
            score += 0.15 * (bigram_matches / len(bigrams))

        if document_title:
            title_lower = document_title.lower()
            title_matches = sum(1 for term in query_terms if term in title_lower)
            score += 0.15 * (title_matches / len(query_terms))

        score += cls._intent_score_adjustment(query_text, haystack)
        return min(score, 1.0)

    @staticmethod
    def _looks_like_overview_query(query_text: str) -> bool:
        """Detect broad overview-style questions about the university."""
        normalized = (query_text or "").strip().lower()
        overview_phrases = (
            "tell me about",
            "what is krmu",
            "what is k r mangalam university",
            "what is kr mangalam university",
            "about krmu",
            "about k.r. mangalam university",
            "about kr mangalam university",
            "university overview",
            "give me an overview",
        )
        return any(phrase in normalized for phrase in overview_phrases)

    @classmethod
    def _intent_score_adjustment(cls, query_text: str, haystack: str) -> float:
        """Adjust lexical scoring for broad overview queries and noisy PDF boilerplate."""
        adjustment = 0.0
        if cls._looks_like_overview_query(query_text):
            overview_markers = (
                "university overview",
                "basic information",
                "full name",
                "established",
                "location",
                "vision",
                "mission",
                "group & history",
                "group and history",
                "ugc",
                "recognised",
            )
            overview_hits = sum(1 for marker in overview_markers if marker in haystack)
            if overview_hits:
                adjustment += min(0.30, 0.12 + (overview_hits * 0.06))

            noisy_markers = (
                "dataset compiled for internal chatbot training purposes",
                "institutional dataset",
                "page ",
                "whatsapp",
                "facebook",
                "instagram",
                "linkedin",
                "youtube",
                "fee payment",
                "seat allotment",
                "phone number",
                "official website",
                "highest ctc",
                "campus recruiters",
                "whatsapp +91",
                "24x7 ambulance",
            )
            noisy_hits = sum(1 for marker in noisy_markers if marker in haystack)
            if noisy_hits:
                adjustment -= min(0.24, noisy_hits * 0.08)

        return adjustment

    @staticmethod
    def _result_signature(item: Dict) -> str:
        """Generate a stable signature for deduplicating near-identical retrieved chunks."""
        title = (item.get("document_title") or "").strip().lower()
        content = re.sub(r"\s+", " ", (item.get("content") or "").strip().lower())
        return f"{title}|{content[:180]}"

    @classmethod
    def _dedupe_ranked_results(cls, items: List[Dict], top_k: int) -> List[Dict]:
        """Drop duplicate chunks that come from repeated uploads of the same content."""
        deduped = []
        seen = set()
        for item in sorted(items, key=lambda entry: entry.get("relevance_score", 0), reverse=True):
            signature = cls._result_signature(item)
            if signature in seen:
                continue
            deduped.append(item)
            seen.add(signature)
            if len(deduped) >= top_k:
                break
        return deduped

    def _detect_collection_dimension(self) -> Optional[int]:
        """Inspect the existing collection and return its embedding dimension if known."""
        try:
            if self.collection.count() == 0:
                return None

            sample = self.collection.get(limit=1, include=["embeddings"])
            embeddings = sample.get("embeddings")
            if embeddings is not None and len(embeddings) > 0 and len(embeddings[0]) > 0:
                return len(embeddings[0])
        except Exception as exc:
            logger.warning("Unable to detect Chroma embedding dimension: %s", exc)

        return None

    def _search_supabase_lexical(self, query: str, top_k: int) -> List[Dict]:
        """Search Supabase chunks lexically when semantic embeddings are unavailable or weak."""
        if not self.supabase:
            return []

        query_terms = self._extract_query_terms(query)
        search_limit = max(40, top_k * 12)

        base_query = self.supabase.table("document_chunks").select(
            "document_id, chunk_index, chunk_text, metadata"
        )

        if query_terms:
            clauses = ",".join([f"chunk_text.ilike.%{term}%" for term in query_terms[:6]])
            response = base_query.or_(clauses).limit(search_limit).execute()
        else:
            response = base_query.limit(search_limit).execute()

        ranked = []
        for row in response.data or []:
            metadata = row.get("metadata") or {}
            title = metadata.get("document_title", "Unknown")
            score = self._score_lexical_match(query, row.get("chunk_text", ""), title)
            if score <= 0:
                continue
            ranked.append(
                {
                    "content": row.get("chunk_text", ""),
                    "document_id": row.get("document_id", ""),
                    "document_title": title,
                    "chunk_index": row.get("chunk_index", 0),
                    "relevance_score": score,
                }
            )

        if not ranked and query_terms:
            # Fallback to a broader scan when a strict ilike filter misses paraphrased content.
            response = base_query.limit(max(120, search_limit)).execute()
            for row in response.data or []:
                metadata = row.get("metadata") or {}
                title = metadata.get("document_title", "Unknown")
                score = self._score_lexical_match(query, row.get("chunk_text", ""), title)
                if score <= 0:
                    continue
                ranked.append(
                    {
                        "content": row.get("chunk_text", ""),
                        "document_id": row.get("document_id", ""),
                        "document_title": title,
                        "chunk_index": row.get("chunk_index", 0),
                        "relevance_score": score,
                    }
                )

        return self._dedupe_ranked_results(ranked, top_k)

    def _search_chroma_lexical(self, query: str, top_k: int) -> List[Dict]:
        """Search locally stored Chroma documents lexically."""
        if self.collection.count() == 0:
            return []

        payload = self.collection.get(include=["documents", "metadatas"])
        documents = payload.get("documents") or []
        metadatas = payload.get("metadatas") or []

        ranked = []
        for doc, meta in zip(documents, metadatas):
            metadata = meta or {}
            title = metadata.get("document_title", "Unknown")
            score = self._score_lexical_match(query, doc or "", title)
            if score <= 0:
                continue
            ranked.append(
                {
                    "content": doc or "",
                    "document_id": metadata.get("document_id", ""),
                    "document_title": title,
                    "chunk_index": metadata.get("chunk_index", 0),
                    "relevance_score": score,
                }
            )

        return self._dedupe_ranked_results(ranked, top_k)

    @staticmethod
    def _merge_ranked_results(primary: List[Dict], secondary: List[Dict], top_k: int) -> List[Dict]:
        """Merge ranked retrieval results without duplicate chunks."""
        merged = []
        seen = set()
        for item in primary + secondary:
            key = (
                item.get("document_id"),
                item.get("chunk_index"),
                RAGEngine._result_signature(item),
            )
            if key in seen:
                continue
            merged.append(item)
            seen.add(key)
        return RAGEngine._dedupe_ranked_results(merged, top_k)

    def _align_embedding_dimension(
        self,
        embedding: List[float],
        target_dimension: Optional[int] = None,
    ) -> List[float]:
        """Match generated embeddings to the persisted collection dimension."""
        dimension = target_dimension or self.embedding_dimension
        if dimension is None:
            if target_dimension is None:
                self.embedding_dimension = len(embedding)
            return embedding

        current_dimension = len(embedding)
        if current_dimension == dimension:
            return embedding

        logger.warning(
            "Adjusting embedding dimension from %s to %s to match the Chroma collection",
            current_dimension,
            dimension,
        )

        if current_dimension > dimension:
            return embedding[:dimension]

        return embedding + ([0.0] * (dimension - current_dimension))

    def _count_chunks(self) -> int:
        """Count stored chunks using Supabase first, then Chroma fallback."""
        if self.use_supabase_vectors:
            try:
                response = self.supabase.table("document_chunks").select("id", count="exact").limit(1).execute()
                if getattr(response, "count", None) is not None:
                    supabase_count = int(response.count)
                    if supabase_count > 0 and self.last_vector_backend_used != "chroma_fallback":
                        return supabase_count
                elif response.data:
                    return len(response.data)
            except Exception as exc:
                logger.warning("Supabase chunk count failed, falling back to Chroma: %s", exc)

        return self.collection.count()

    @staticmethod
    def _serialize_embedding(embedding: List[float]) -> str:
        """Serialize an embedding in the vector text format expected by pgvector."""
        return json.dumps([float(value) for value in embedding])

    def _upsert_supabase_chunk(
        self,
        document_id: str,
        chunk_index: int,
        chunk_text: str,
        embedding: List[float],
        metadata: Dict,
    ) -> bool:
        """Write a single chunk to Supabase via RPC."""
        if not self.supabase:
            return False

        response = self.supabase.rpc(
            "upsert_document_chunk",
            {
                "p_document_id": document_id,
                "p_chunk_index": chunk_index,
                "p_chunk_text": chunk_text,
                "p_embedding_text": self._serialize_embedding(embedding),
                "p_metadata": metadata,
            },
        ).execute()
        return bool(response.data)

    def _search_supabase(self, query_embedding: List[float], top_k: int) -> List[Dict]:
        """Search Supabase pgvector chunks using the SQL RPC helper."""
        if not self.supabase:
            return []

        response = self.supabase.rpc(
            "match_document_chunks",
            {
                "query_embedding_text": self._serialize_embedding(query_embedding),
                "match_count": max(1, top_k),
                "match_document_id": None,
            },
        ).execute()

        retrieved = []
        for row in response.data or []:
            metadata = row.get("metadata") or {}
            retrieved.append(
                {
                    "content": row.get("chunk_text", ""),
                    "document_id": row.get("document_id", ""),
                    "document_title": metadata.get("document_title", "Unknown"),
                    "chunk_index": row.get("chunk_index", 0),
                    "relevance_score": row.get("similarity", 0),
                }
            )

        return retrieved

    def _delete_supabase_document(self, document_id: str) -> bool:
        """Delete all stored chunks for a document from Supabase."""
        if not self.supabase:
            return False

        response = self.supabase.rpc(
            "delete_document_chunks",
            {"p_document_id": document_id},
        ).execute()
        deleted_rows = response.data or 0
        return bool(deleted_rows)

    def _build_messages(
        self,
        query: str,
        context_docs: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Build a grounded chat prompt from retrieved document chunks."""
        context_parts = []
        for index, doc in enumerate(context_docs[:3], 1):
            context_parts.append(f"[Source {index}: {doc['document_title']}]\n{doc['content']}")

        context = "\n\n".join(context_parts)

        system_prompt = """You are an academic assistant for K.R. Mangalam University.

Rules:
- Use ONLY the provided knowledge-base context and recent conversation history
- Do not guess, invent, or fill gaps from general knowledge
- If the context is missing a fact, say that clearly and ask a narrower follow-up
- Keep answers concise, accurate, student-friendly, and easy to scan
- When citing facts, mention the relevant source title naturally in the answer
- Prefer short bullets for factual answers instead of long paragraphs
- For greetings or small talk, respond warmly, explain what topics you can help with, and suggest 2 or 3 concrete next questions

Answer quality checklist:
- Start with the direct answer
- Include only the most relevant details
- Avoid repeating the whole question
- If multiple sources agree, synthesize them instead of listing raw snippets
- Do not mention numbers, dates, fees, rankings, approvals, contacts, or counts unless they appear in the context
- If a fact is only partially supported, say "Based on the indexed document..." instead of stating it as certain

Required format for non-greeting answers:
1. Start with a one-line "Direct answer:" sentence
2. Then add a "Key points:" section with 2 to 4 short bullet points
3. End with a "Source:" line naming the most relevant document title
4. If the context is incomplete, add a final line: "What I could not verify from the indexed docs:" followed by the missing point"""

        history_parts = []
        for turn in (conversation_history or [])[-6:]:
            role = turn.get("role", "user")
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            history_parts.append(f"{role.title()}: {content}")
        conversation_context = "\n".join(history_parts)

        user_prompt = f"""Recent Conversation:
{conversation_context or "No previous conversation."}

Context from SET Knowledge Base:
{context}

Question: {query}

Write the best grounded answer you can using only the context above. Keep it factual, well-structured, and easy to read. If the context is insufficient, say so clearly instead of guessing."""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _build_web_messages(
        self,
        query: str,
        web_results: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Build a prompt that synthesizes DuckDuckGo snippets without inventing details."""
        result_parts = []
        for index, result in enumerate(web_results[:4], 1):
            result_parts.append(
                f"[Web Source {index}: {result.get('title', 'Untitled')}]\n"
                f"Snippet: {result.get('snippet', '')}\n"
                f"URL: {result.get('url', '')}"
            )

        web_context = "\n\n".join(result_parts)

        history_parts = []
        for turn in (conversation_history or [])[-6:]:
            role = turn.get("role", "user")
            content = (turn.get("content") or "").strip()
            if content:
                history_parts.append(f"{role.title()}: {content}")
        conversation_context = "\n".join(history_parts)

        system_prompt = """You are a careful web-assisted university assistant.

Rules:
- Use ONLY the provided DuckDuckGo search snippets and recent conversation history
- Do not claim facts that are not supported by the snippets
- If snippets are incomplete or conflicting, say that clearly
- Keep the answer concise and useful
- Mention the source title or site when giving factual points
- End with a short caution that the user should verify important details on the official page when appropriate"""

        user_prompt = f"""Recent Conversation:
{conversation_context or "No previous conversation."}

DuckDuckGo Search Results:
{web_context or "No web results were found."}

Question: {query}

Summarize the most reliable answer supported by the snippets above."""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _chat_with_fallback(self, messages: List[Dict], temperature: float = 0.7) -> str:
        """Use the remote LLM first, then fall back to Ollama automatically."""
        if self.remote_llm.is_available:
            try:
                return self.remote_llm.chat(messages, temperature=temperature)
            except Exception as exc:
                logger.warning("Remote LLM chat failed, falling back to Ollama: %s", exc)

        return self.ollama.chat(messages, temperature=temperature)

    @staticmethod
    def _looks_like_greeting(query: str) -> bool:
        lowered = (query or "").strip().lower()
        greeting_tokens = [
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
            "can you help me",
            "help me",
        ]
        return lowered in greeting_tokens or any(lowered.startswith(f"{token} ") for token in greeting_tokens)

    @staticmethod
    def _clean_snippet(text: str, limit: int = 220) -> str:
        snippet = " ".join((text or "").split())
        snippet = re.sub(
            r"source:\s*krmangalam\.edu\.in\s*\|\s*dataset compiled for internal chatbot training purposes",
            "",
            snippet,
            flags=re.IGNORECASE,
        )
        snippet = re.sub(
            r"kr mangalam university\s*[—-]\s*institutional dataset\s*[—-]?\s*\(chatbot training\)",
            "",
            snippet,
            flags=re.IGNORECASE,
        )
        snippet = re.sub(r"\bpage\s+\d+\b", "", snippet, flags=re.IGNORECASE)
        snippet = re.sub(r"\bversion:\s*[\w\-.]+\b", "", snippet, flags=re.IGNORECASE)
        snippet = re.sub(r"\bcompiled from:\s*krmangalam\.edu\.in\b", "", snippet, flags=re.IGNORECASE)
        snippet = re.sub(r"\bpurpose:\s*training data for university information chatbot\.?", "", snippet, flags=re.IGNORECASE)
        snippet = re.sub(r"\s+\|\s+", " | ", snippet)
        snippet = re.sub(r"\s{2,}", " ", snippet).strip(" |,-")
        if snippet.startswith("# "):
            snippet = snippet.split(" ", 2)[-1]
        if len(snippet) > limit:
            snippet = snippet[:limit].rstrip() + "..."
        return snippet

    def _compose_grounded_fallback(
        self,
        query: str,
        context_docs: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
    ) -> str:
        """Build a lightweight answer directly from retrieved chunks when generation fails."""
        if not context_docs:
            return (
                "I couldn't find enough grounded information in the indexed knowledge base to answer that yet. "
                "Try rephrasing the question or asking about admissions, faculty, fees, infrastructure, placements, or hostels."
            )

        if self._looks_like_greeting(query):
            return (
                "Hello! I'm here to help with K.R. Mangalam University information.\n\n"
                "You can ask me about admissions, faculty, fees, infrastructure, hostels, placements, library, or programmes.\n\n"
                "Try one of these:\n"
                "- What are the admission requirements for B.Tech?\n"
                "- Tell me about SET placements\n"
                "- What facilities are available on campus?"
            )

        top_docs = context_docs[:2]
        latest_user_topic = ""
        for turn in reversed(conversation_history or []):
            if turn.get("role") == "user":
                latest_user_topic = (turn.get("content") or "").strip()
                if latest_user_topic:
                    break

        lead = "Direct answer: Here is what I found in the KRMU knowledge base."
        if latest_user_topic and query.strip().lower() in {"what about the fees?", "and fees?", "what about fees?", "fees?"}:
            lead = f"Direct answer: Continuing from your earlier question about \"{latest_user_topic}\", here is what I found."

        first_doc = top_docs[0]
        first_title = first_doc.get("document_title", "Unknown source")
        first_snippet = self._clean_snippet(first_doc.get("content", ""))

        response_parts = [
            lead,
            "",
            "Key points:",
            f"- {first_snippet}",
            "",
            f"Source: {first_title}",
        ]

        if len(top_docs) > 1:
            second_doc = top_docs[1]
            second_title = second_doc.get("document_title", "Unknown source")
            second_snippet = self._clean_snippet(second_doc.get("content", ""))
            response_parts.extend(
                [
                    "",
                    f"- Also relevant: {second_snippet}",
                    f"Additional source: {second_title}",
                ]
            )

        response_parts.extend(
            [
                "",
                "If you want, I can answer a more specific follow-up on this.",
            ]
        )

        return "\n".join(response_parts)

    async def _stream_with_fallback(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream from the remote LLM first, then fall back to Ollama."""
        if self.remote_llm.is_available:
            try:
                async for chunk in self.remote_llm.stream_chat(messages, temperature=temperature):
                    yield chunk
                return
            except Exception as exc:
                logger.warning("Remote LLM stream failed, falling back to Ollama: %s", exc)

        async for chunk in self.ollama.stream_chat(messages, temperature=temperature):
            yield chunk

    def add_document_chunks(
        self,
        document_id: str,
        document_title: str,
        chunks: List[str],
        metadata: Optional[Dict] = None,
    ) -> int:
        """Add document chunks to the vector store."""
        if not chunks:
            return 0

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        supabase_success = True

        for index, chunk in enumerate(chunks):
            if not chunk.strip():
                continue

            chunk_id = f"{document_id}_chunk_{index}"
            raw_embedding = self._generate_embedding(chunk)
            embedding = self._align_embedding_dimension(
                raw_embedding,
                target_dimension=(
                    self.supabase_embedding_dimension
                    if self.use_supabase_vectors
                    else self.chroma_embedding_dimension
                ),
            )

            chunk_metadata = {
                "document_id": document_id,
                "document_title": document_title,
                "chunk_index": index,
                **(metadata or {}),
            }

            ids.append(chunk_id)
            embeddings.append(embedding)
            documents.append(chunk)
            metadatas.append(chunk_metadata)

            if self.use_supabase_vectors and supabase_success:
                try:
                    self._upsert_supabase_chunk(
                        document_id=document_id,
                        chunk_index=index,
                        chunk_text=chunk,
                        embedding=embedding,
                        metadata=chunk_metadata,
                    )
                except Exception as exc:
                    supabase_success = False
                    logger.warning(
                        "Supabase vector upsert failed for document %s chunk %s, falling back to Chroma: %s",
                        document_id,
                        index,
                        exc,
                    )
                    continue

        if self.use_supabase_vectors and not supabase_success:
            try:
                self._delete_supabase_document(document_id)
            except Exception as cleanup_error:
                logger.warning(
                    "Failed to clean up partial Supabase chunks for document %s: %s",
                    document_id,
                    cleanup_error,
                )

        if ids and (not self.use_supabase_vectors or not supabase_success):
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
            self.last_vector_backend_used = "chroma_fallback" if self.use_supabase_vectors else "chroma"
            logger.info("Added %s chunks for document %s", len(ids), document_id)
        elif ids:
            self.last_vector_backend_used = "supabase"
            logger.info("Added %s chunks for document %s to Supabase pgvector", len(ids), document_id)

        return len(ids)

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Search for relevant document chunks."""
        lexical_results: List[Dict] = []
        if self.use_supabase_vectors:
            try:
                lexical_results = self._search_supabase_lexical(query, top_k)
            except Exception as exc:
                logger.warning("Supabase lexical search failed: %s", exc)
        else:
            try:
                lexical_results = self._search_chroma_lexical(query, top_k)
            except Exception as exc:
                logger.warning("Chroma lexical search failed: %s", exc)

        # If no real embedding model is available, lexical retrieval is the most reliable mode.
        if not self._has_semantic_embeddings():
            if lexical_results:
                self.last_vector_backend_used = "supabase_lexical" if self.use_supabase_vectors else "chroma_lexical"
                return lexical_results
            return []

        raw_query_embedding = self._generate_embedding(query)
        query_embedding = self._align_embedding_dimension(
            raw_query_embedding,
            target_dimension=(
                self.supabase_embedding_dimension
                if self.use_supabase_vectors
                else self.chroma_embedding_dimension
            ),
        )

        if self.use_supabase_vectors:
            try:
                results = self._search_supabase(query_embedding, top_k)
                if results:
                    self.last_vector_backend_used = "supabase"
                    if lexical_results and max(result.get("relevance_score", 0) for result in results) < 0.45:
                        self.last_vector_backend_used = "supabase_lexical"
                        return self._merge_ranked_results(lexical_results, results, top_k)
                    return self._merge_ranked_results(results, lexical_results, top_k)
            except Exception as exc:
                logger.warning("Supabase vector search failed, falling back to Chroma: %s", exc)

        if self.collection.count() == 0:
            return []

        query_embedding = self._align_embedding_dimension(
            raw_query_embedding,
            target_dimension=self.chroma_embedding_dimension,
        )

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, self.collection.count()),
                include=["documents", "metadatas", "distances"],
            )
        except InvalidArgumentError:
            refreshed_dimension = self._detect_collection_dimension()
            if refreshed_dimension:
                self.chroma_embedding_dimension = refreshed_dimension
                if not self.use_supabase_vectors:
                    self.embedding_dimension = refreshed_dimension
                query_embedding = self._align_embedding_dimension(
                    raw_query_embedding,
                    target_dimension=self.chroma_embedding_dimension,
                )
                results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(top_k, self.collection.count()),
                    include=["documents", "metadatas", "distances"],
                )
            else:
                raise

        retrieved = []
        if results and results.get("documents"):
            self.last_vector_backend_used = "chroma_fallback" if self.use_supabase_vectors else "chroma"
            for doc, meta, distance in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                retrieved.append(
                    {
                        "content": doc,
                        "document_id": meta.get("document_id", ""),
                        "document_title": meta.get("document_title", "Unknown"),
                        "chunk_index": meta.get("chunk_index", 0),
                        "relevance_score": 1 - distance,
                    }
                )

        if retrieved:
            if lexical_results and max(doc.get("relevance_score", 0) for doc in retrieved) < 0.45:
                self.last_vector_backend_used = "chroma_lexical"
                return self._merge_ranked_results(lexical_results, retrieved, top_k)
            return self._merge_ranked_results(retrieved, lexical_results, top_k)

        if lexical_results:
            self.last_vector_backend_used = "chroma_lexical" if not self.use_supabase_vectors else "supabase_lexical"
            return lexical_results

        return []

    def format_sources(self, retrieved_docs: List[Dict]) -> List[Dict]:
        """Format retrieved chunks into unique source citations."""
        sources = []
        seen_docs = set()

        for doc in retrieved_docs:
            doc_id = doc["document_id"]
            if doc_id in seen_docs:
                continue

            sources.append(
                {
                    "document_id": doc_id,
                    "document_title": doc["document_title"],
                    "chunk_text": (
                        doc["content"][:200] + "..."
                        if len(doc["content"]) > 200
                        else doc["content"]
                    ),
                    "relevance_score": doc["relevance_score"],
                }
            )
            seen_docs.add(doc_id)

        return sources[:3]

    def get_document_chunks_preview(self, document_id: str, limit: int = 8) -> List[Dict]:
        """Fetch a small preview of stored chunks for a document."""
        preview_limit = max(1, min(limit, 12))

        if self.use_supabase_vectors and self.supabase:
            response = (
                self.supabase.table("document_chunks")
                .select("chunk_index, chunk_text, metadata")
                .eq("document_id", document_id)
                .order("chunk_index")
                .limit(preview_limit)
                .execute()
            )
            return [
                {
                    "chunk_index": row.get("chunk_index", 0),
                    "chunk_text": self._clean_snippet(row.get("chunk_text", ""), limit=320),
                    "metadata": row.get("metadata") or {},
                }
                for row in (response.data or [])
            ]

        try:
            payload = self.collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
            documents = payload.get("documents") or []
            metadatas = payload.get("metadatas") or []
            rows = []
            for doc, metadata in zip(documents, metadatas):
                meta = metadata or {}
                rows.append(
                    {
                        "chunk_index": meta.get("chunk_index", 0),
                        "chunk_text": self._clean_snippet(doc or "", limit=320),
                        "metadata": meta,
                    }
                )
            rows.sort(key=lambda item: item.get("chunk_index", 0))
            return rows[:preview_limit]
        except Exception as exc:
            logger.warning("Chunk preview fetch failed for %s: %s", document_id, exc)
            return []

    def evaluate_retrieval(self, query: str, top_k: int = 5) -> Dict:
        """Run a retrieval-only debug pass without generating a chat answer."""
        retrieved_docs = self.search(query, top_k=top_k)
        results = [
            {
                "chunk_index": doc.get("chunk_index", 0),
                "chunk_text": self._clean_snippet(doc.get("content", ""), limit=320),
                "relevance_score": doc.get("relevance_score", 0),
                "metadata": {
                    "document_id": doc.get("document_id", ""),
                    "document_title": doc.get("document_title", "Unknown"),
                },
            }
            for doc in retrieved_docs[:top_k]
        ]
        return {
            "query": query,
            "vector_backend": self.last_vector_backend_used,
            "embedding_provider": self._embedding_provider_name(),
            "embedding_model": self._embedding_model_name(),
            "chunk_count": len(results),
            "results": results,
        }

    @staticmethod
    def _filter_relevant_docs(retrieved_docs: List[Dict], min_score: float = 0.45) -> List[Dict]:
        """Keep only sufficiently relevant chunks for answer generation."""
        filtered_docs = [doc for doc in retrieved_docs if doc.get("relevance_score", 0) >= min_score]
        return filtered_docs or retrieved_docs[:1]

    def generate_response(
        self,
        query: str,
        context_docs: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
    ) -> str:
        """Generate a grounded response using the best available chat provider."""
        if not context_docs:
            return (
                "I couldn't find relevant information in the indexed knowledge base for that question yet. "
                "Please try rephrasing it or ask about admissions, faculty, fees, infrastructure, placements, hostels, or academics."
            )

        messages = self._build_messages(query, context_docs, conversation_history=conversation_history)
        try:
            return self._chat_with_fallback(messages, temperature=0.15)
        except Exception as exc:
            logger.warning("LLM response generation failed, using grounded fallback answer: %s", exc)
            return self._compose_grounded_fallback(query, context_docs, conversation_history=conversation_history)

    def generate_web_response(
        self,
        query: str,
        web_results: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
    ) -> str:
        """Generate an internet-mode answer grounded only in DuckDuckGo snippets."""
        if not web_results:
            return (
                "I couldn't find enough relevant DuckDuckGo results for that question right now. "
                "Try a more specific query or switch to database mode for indexed campus documents."
            )

        messages = self._build_web_messages(query, web_results, conversation_history=conversation_history)
        try:
            return self._chat_with_fallback(messages, temperature=0.2)
        except Exception as exc:
            logger.warning("Web response generation failed, using snippet fallback: %s", exc)
            top_result = web_results[0]
            return (
                f"From the web results, the strongest match is \"{top_result.get('title', 'Untitled source')}\". "
                f"{self._clean_snippet(top_result.get('snippet', ''))}\n\n"
                f"Source: {top_result.get('url', 'Unavailable')}"
            )

    async def stream_response(
        self,
        query: str,
        context_docs: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
    ) -> AsyncIterator[str]:
        """Stream a grounded response using the best available chat provider."""
        relevant_docs = self._filter_relevant_docs(context_docs)
        if not relevant_docs:
            yield (
                "I couldn't find relevant information in the indexed knowledge base for that question yet. "
                "Please try rephrasing it or ask about admissions, faculty, fees, infrastructure, placements, hostels, or academics."
            )
            return

        messages = self._build_messages(query, relevant_docs, conversation_history=conversation_history)
        try:
            async for chunk in self._stream_with_fallback(messages, temperature=0.15):
                yield chunk
        except Exception as exc:
            logger.warning("Streaming generation failed, using grounded fallback answer: %s", exc)
            yield self._compose_grounded_fallback(query, relevant_docs, conversation_history=conversation_history)

    def chat(
        self,
        query: str,
        top_k: int = 3,
        conversation_history: Optional[List[Dict]] = None,
    ) -> Dict:
        """Complete RAG chat: retrieve context and generate a non-streaming response."""
        retrieved_docs = self.search(query, top_k=top_k)
        relevant_docs = self._filter_relevant_docs(retrieved_docs)
        response = self.generate_response(query, relevant_docs, conversation_history=conversation_history)
        return {
            "response": response,
            "sources": self.format_sources(relevant_docs),
        }

    def delete_document(self, document_id: str) -> bool:
        """Delete all chunks for a document."""
        deleted = False
        if self.use_supabase_vectors:
            try:
                deleted = self._delete_supabase_document(document_id) or deleted
            except Exception as exc:
                logger.warning("Supabase chunk deletion failed for %s: %s", document_id, exc)

        try:
            results = self.collection.get(where={"document_id": document_id})
            if results and results.get("ids"):
                self.collection.delete(ids=results["ids"])
                logger.info("Deleted %s Chroma chunks for document %s", len(results["ids"]), document_id)
                deleted = True
            return deleted
        except Exception as exc:
            logger.error("Error deleting document %s: %s", document_id, exc)
            return deleted

    def get_stats(self) -> Dict:
        """Get statistics about the vector store and active model providers."""
        chat_provider = "fallback"
        chat_model = "fallback"
        if self.remote_llm.is_available:
            chat_provider = "vllm"
            chat_model = self.remote_llm.model
        elif self.ollama.is_available:
            chat_provider = "ollama"
            chat_model = OLLAMA_CHAT_MODEL

        return {
            "total_chunks": self._count_chunks(),
            "storage_path": self.storage_path,
            "vector_backend": self.last_vector_backend_used,
            "vector_store_mode": "supabase_with_chroma_fallback" if self.use_supabase_vectors else "chroma_only",
            "embedding_dimension": self.embedding_dimension,
            "embedding_provider": self._embedding_provider_name(),
            "chat_provider": chat_provider,
            "chat_model": chat_model,
            "remote_llm_available": self.remote_llm.is_available,
            "remote_llm_base_url": self.remote_llm.base_url or None,
            "remote_llm_model": self.remote_llm.model,
            "remote_llm_models": self.remote_llm.list_models() if self.remote_llm.is_available else [],
            "ollama_available": self.ollama.is_available,
            "ollama_models": self.ollama.list_models() if self.ollama.is_available else [],
            "embedding_model": self._embedding_model_name(),
        }

    def refresh_model_connections(self) -> Dict[str, bool]:
        """Refresh both remote and local model provider connections."""
        self.remote_llm._check_availability()
        self.remote_embeddings._check_availability()
        self.ollama._check_availability()
        return {
            "remote_llm_available": self.remote_llm.is_available,
            "ollama_available": self.ollama.is_available,
            "remote_embeddings_available": self.remote_embeddings.is_available,
        }

    def refresh_ollama_connection(self):
        """Backward-compatible wrapper for existing frontend/admin actions."""
        status = self.refresh_model_connections()
        return status["ollama_available"]


# Global RAG engine instance
rag_engine = RAGEngine()
