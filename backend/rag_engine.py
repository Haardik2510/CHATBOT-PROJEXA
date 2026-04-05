"""RAG Engine using Supabase pgvector or ChromaDB with OpenAI-compatible and Ollama chat backends."""
import json
import os
import logging
import hashlib
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

        system_prompt = """You are an intelligent academic assistant for K.R. Mangalam University. Your role is to help students, faculty, and staff with accurate information based on the provided context.

Guidelines:
- Answer questions accurately based ONLY on the provided context and recent conversation history
- Always cite the source document title when referencing specific facts
- If the context does not contain enough information, say so clearly instead of guessing
- Be warm, natural, and concise without sounding robotic
- When helpful, end with one short follow-up question that keeps the conversation moving
- Prefer short paragraphs or bullets over long walls of text
- For greetings or small talk, respond naturally and invite the user to ask about admissions, faculty, fees, infrastructure, placements, hostels, library, or academics"""

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

Please provide a helpful, accurate answer based on the context above. Cite the source documents when referencing specific information."""

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
        return any(token in lowered for token in greeting_tokens)

    @staticmethod
    def _clean_snippet(text: str, limit: int = 220) -> str:
        snippet = " ".join((text or "").split())
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
                "What would you like to know first?"
            )

        top_docs = context_docs[:2]
        latest_user_topic = ""
        for turn in reversed(conversation_history or []):
            if turn.get("role") == "user":
                latest_user_topic = (turn.get("content") or "").strip()
                if latest_user_topic:
                    break

        lead = "Here’s what I found in the KRMU knowledge base."
        if latest_user_topic and query.strip().lower() in {"what about the fees?", "and fees?", "what about fees?", "fees?"}:
            lead = f"Continuing from your earlier question about \"{latest_user_topic}\", here’s what I found."

        first_doc = top_docs[0]
        first_title = first_doc.get("document_title", "Unknown source")
        first_snippet = self._clean_snippet(first_doc.get("content", ""))

        response_parts = [
            lead,
            "",
            f"{first_snippet}",
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
                    f"Also relevant: {second_snippet}",
                    f"Source: {second_title}",
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
            raw_embedding = self.ollama.generate_embedding(chunk)
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
        raw_query_embedding = self.ollama.generate_embedding(query)
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
                    return results
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

        return retrieved

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
            return self._chat_with_fallback(messages, temperature=0.3)
        except Exception as exc:
            logger.warning("LLM response generation failed, using grounded fallback answer: %s", exc)
            return self._compose_grounded_fallback(query, context_docs, conversation_history=conversation_history)

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
            async for chunk in self._stream_with_fallback(messages, temperature=0.3):
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
            "chat_provider": chat_provider,
            "chat_model": chat_model,
            "remote_llm_available": self.remote_llm.is_available,
            "remote_llm_base_url": self.remote_llm.base_url or None,
            "remote_llm_model": self.remote_llm.model,
            "remote_llm_models": self.remote_llm.list_models() if self.remote_llm.is_available else [],
            "ollama_available": self.ollama.is_available,
            "ollama_models": self.ollama.list_models() if self.ollama.is_available else [],
            "embedding_model": OLLAMA_EMBEDDING_MODEL if self.ollama.is_available else "hash-based",
        }

    def refresh_model_connections(self) -> Dict[str, bool]:
        """Refresh both remote and local model provider connections."""
        self.remote_llm._check_availability()
        self.ollama._check_availability()
        return {
            "remote_llm_available": self.remote_llm.is_available,
            "ollama_available": self.ollama.is_available,
        }

    def refresh_ollama_connection(self):
        """Backward-compatible wrapper for existing frontend/admin actions."""
        status = self.refresh_model_connections()
        return status["ollama_available"]


# Global RAG engine instance
rag_engine = RAGEngine()
