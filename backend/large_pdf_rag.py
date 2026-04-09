"""Production-style hybrid RAG pipeline for very large PDFs."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import gc
import hashlib
import json
import logging
import math
import multiprocessing
import os
import pickle
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple

import chromadb
import fitz
import requests
from chromadb.config import Settings
from openai import OpenAI
from tqdm import tqdm


LOGGER = logging.getLogger("large_pdf_rag")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_STORAGE_DIR = ROOT_DIR / "rag_store"
DEFAULT_CHROMA_DIR = DEFAULT_STORAGE_DIR / "chroma"
DEFAULT_INDEX_DIR = DEFAULT_STORAGE_DIR / "indexes"
DEFAULT_CACHE_DIR = DEFAULT_STORAGE_DIR / "cache"
DEFAULT_IMAGE_DIR = DEFAULT_CACHE_DIR / "images"
DEFAULT_EMBED_CACHE = DEFAULT_CACHE_DIR / "embedding_cache.sqlite3"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-1.5-flash"
RRF_K = 60
PAGE_BATCH_SIZE = 5
EMBED_BATCH_SIZE = 16
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MIN_CHUNK_CHARS = 100
RETRIEVE_TOP_K = 6
RERANK_TOP_K = 3
QUERY_EMBED_PREFIX = "Represent this sentence for searching: "

_EMBEDDER: Optional[Any] = None
_RERANKER: Optional[Any] = None


@dataclass
class PageRecord:
    page_number: int
    source_file: str
    text: str
    section_heading: str
    blocks: List[str]
    images: List[Dict]
    image_descriptions: List[str]
    is_text_page: bool
    heading_candidates: List[Tuple[str, float]]


@dataclass
class ChunkRecord:
    id: str
    text: str
    metadata: Dict


def _ensure_directories() -> None:
    for path in (DEFAULT_STORAGE_DIR, DEFAULT_CHROMA_DIR, DEFAULT_INDEX_DIR, DEFAULT_CACHE_DIR, DEFAULT_IMAGE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "collection"


def _pdf_fingerprint(pdf_path: str) -> str:
    stat = os.stat(pdf_path)
    raw = f"{os.path.abspath(pdf_path)}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", _normalize_text(line)).strip(" |")


def _strip_common_noise(text: str) -> str:
    cleaned_lines: List[str] = []
    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        if len(line) < 20:
            continue
        if re.fullmatch(r"(page\s*)?\d+(\s*/\s*\d+)?", line, flags=re.IGNORECASE):
            continue
        if re.fullmatch(r"[ivxlcdm]+", line.lower()):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _sentence_split(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text) if part.strip()]


def _extract_heading(candidate_lines: Sequence[str]) -> str:
    for line in candidate_lines[:8]:
        compact = _clean_line(line)
        if len(compact) < 8 or len(compact) > 120:
            continue
        if compact.endswith("."):
            continue
        alpha = sum(ch.isalpha() for ch in compact)
        if alpha < 6:
            continue
        words = compact.split()
        title_case = sum(word[:1].isupper() for word in words) >= max(1, len(words) // 2)
        if title_case or compact.isupper():
            return compact
    return "Document Content"


def _extract_heading_from_font_candidates(candidates: Sequence[Tuple[str, float]]) -> str:
    ranked = sorted(
        (
            (_clean_line(text), float(size))
            for text, size in candidates
            if _clean_line(text)
        ),
        key=lambda item: (item[1], len(item[0])),
        reverse=True,
    )
    for text, _size in ranked:
        if len(text) < 8 or len(text) > 160:
            continue
        if text.endswith("."):
            continue
        alpha = sum(ch.isalpha() for ch in text)
        if alpha < 6:
            continue
        return text
    return _extract_heading([text for text, _size in candidates])


def _tokenize_for_bm25(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _sigmoid(value: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-value))
    except OverflowError:
        return 0.0 if value < 0 else 1.0


def _chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """SQLite cache so identical chunks are not re-embedded after restarts."""

    def __init__(self, db_path: Path = DEFAULT_EMBED_CACHE):
        _ensure_directories()
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    text_hash TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    PRIMARY KEY (text_hash, model_name)
                )
                """
            )

    def get_many(self, texts: Sequence[str], model_name: str) -> Dict[str, List[float]]:
        keys = [_chunk_hash(text) for text in texts]
        if not keys:
            return {}

        placeholders = ",".join("?" for _ in keys)
        query = (
            f"SELECT text_hash, embedding_json FROM embeddings "
            f"WHERE model_name = ? AND text_hash IN ({placeholders})"
        )
        with self._connect() as conn:
            rows = conn.execute(query, [model_name, *keys]).fetchall()
        return {text_hash: json.loads(embedding_json) for text_hash, embedding_json in rows}

    def set_many(self, mapping: Dict[str, List[float]], model_name: str) -> None:
        if not mapping:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO embeddings (text_hash, model_name, embedding_json)
                VALUES (?, ?, ?)
                """,
                [(text_hash, model_name, json.dumps(vector)) for text_hash, vector in mapping.items()],
            )


class GeminiImageAnalyzer:
    """Gemini 1.5 Flash image describer for PDF visuals."""

    def __init__(self, api_key: Optional[str] = None, model: str = GEMINI_MODEL):
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = model
        self.is_available = bool(self.api_key)

    def describe(self, image_bytes: bytes, page_number: int, source_file: str) -> Optional[str]:
        if not self.is_available or not image_bytes:
            return None

        try:
            encoded = base64.b64encode(image_bytes).decode("utf-8")
            mime_type = "image/png"
            if image_bytes.startswith(b"\xff\xd8"):
                mime_type = "image/jpeg"
            elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
                mime_type = "image/webp"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    "Describe this PDF image for retrieval in a university RAG system. "
                                    "Focus only on visible factual details such as charts, figures, captions, "
                                    "signage, event banners, building names, or tables. Keep it under 90 words."
                                )
                            },
                            {"inline_data": {"mime_type": mime_type, "data": encoded}},
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.1, "topP": 0.8, "maxOutputTokens": 180},
            }
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                params={"key": self.api_key},
                json=payload,
                timeout=45,
            )
            response.raise_for_status()
            data = response.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = " ".join(part.get("text", "").strip() for part in parts if part.get("text"))
            text = _normalize_text(text)
            if not text:
                return None
            return f"Image description from page {page_number} of {Path(source_file).name}: {text}"
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Gemini image analysis failed for page %s: %s", page_number, exc)
            return None


class HybridIndexStore:
    """Persist chunk sidecars so BM25 can be rebuilt or cached locally."""

    def __init__(self, collection_name: str):
        self.collection_name = _slugify(collection_name)
        self.index_dir = DEFAULT_INDEX_DIR / self.collection_name
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.index_dir / "chunks.jsonl"
        self.bm25_path = self.index_dir / "bm25.pkl"

    def write_records(self, chunks: Sequence[ChunkRecord]) -> None:
        with self.records_path.open("w", encoding="utf-8") as handle:
            for chunk in chunks:
                handle.write(
                    json.dumps({"id": chunk.id, "text": chunk.text, "metadata": chunk.metadata}, ensure_ascii=False) + "\n"
                )
        if self.bm25_path.exists():
            self.bm25_path.unlink()

    def merge_records(self, chunks: Sequence[ChunkRecord]) -> None:
        existing = {record["id"]: record for record in self.load_records()}
        for chunk in chunks:
            existing[chunk.id] = {"id": chunk.id, "text": chunk.text, "metadata": chunk.metadata}
        merged = [
            ChunkRecord(id=record["id"], text=record["text"], metadata=record.get("metadata") or {})
            for record in existing.values()
        ]
        self.write_records(merged)

    def load_records(self) -> List[Dict]:
        if not self.records_path.exists():
            return []
        with self.records_path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def load_or_build_bm25(self) -> Tuple[Any, List[Dict]]:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as exc:
            raise RuntimeError(
                "Large PDF hybrid retrieval requires the optional dependency 'rank-bm25'."
            ) from exc

        records = self.load_records()
        if not records:
            raise FileNotFoundError(f"No stored chunks found for collection '{self.collection_name}'")

        if self.bm25_path.exists():
            with self.bm25_path.open("rb") as handle:
                payload = pickle.load(handle)
            return payload["bm25"], payload["records"]

        tokenized = [_tokenize_for_bm25(record["text"]) for record in records]
        bm25 = BM25Okapi(tokenized)
        with self.bm25_path.open("wb") as handle:
            pickle.dump({"bm25": bm25, "records": records}, handle)
        return bm25, records


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Large PDF indexing requires the optional dependency 'sentence-transformers'."
            ) from exc
        _EMBEDDER = SentenceTransformer("BAAI/bge-m3")
    return _EMBEDDER


def _get_reranker():
    global _RERANKER
    if _RERANKER is None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "Large PDF reranking requires the optional dependency 'sentence-transformers'."
            ) from exc
        _RERANKER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    return _RERANKER


def _iter_page_batches(total_pages: int, batch_size: int = PAGE_BATCH_SIZE) -> Generator[Tuple[int, int], None, None]:
    for start in range(0, total_pages, batch_size):
        yield start, min(start + batch_size, total_pages)


def _extract_page_batch_worker(pdf_path: str, start_page: int, end_page: int, image_dir: str) -> List[Dict]:
    """Extract a small page range in a separate process for better throughput."""
    document = fitz.open(pdf_path)
    batch_records: List[Dict] = []
    pdf_name = Path(pdf_path).name
    pdf_hash = _pdf_fingerprint(pdf_path)

    for page_index in range(start_page, end_page):
        page = document.load_page(page_index)
        page_number = page_index + 1
        text_dict = page.get_text("dict")
        text_blocks = []
        top_lines: List[str] = []
        bottom_lines: List[str] = []
        candidate_lines: List[str] = []
        heading_candidates: List[Tuple[str, float]] = []

        sorted_blocks = sorted(text_dict.get("blocks", []), key=lambda block: (block["bbox"][1], block["bbox"][0]))
        for block in sorted_blocks:
            if block.get("type") != 0:
                continue
            block_lines: List[str] = []
            for line in block.get("lines", []):
                spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
                joined = _clean_line("".join(span.get("text", "") for span in spans))
                if not joined:
                    continue
                block_lines.append(joined)
                candidate_lines.append(joined)
                max_font_size = max((float(span.get("size", 0.0) or 0.0) for span in spans), default=0.0)
                heading_candidates.append((joined, max_font_size))
                if len(top_lines) < 2:
                    top_lines.append(joined)
                bottom_lines = (bottom_lines + [joined])[-2:]
            if block_lines:
                text_blocks.append("\n".join(block_lines))

        table_like_blocks: List[str] = []
        for block in page.get_text("blocks"):
            block_text = _clean_line(block[4])
            if block_text and ("  " in block[4] or "\t" in block[4]):
                table_like_blocks.append(block_text)

        full_text = "\n\n".join(text_blocks + table_like_blocks)
        page_images: List[Dict] = []
        for image_index, image_ref in enumerate(page.get_images(full=True)):
            try:
                xref = image_ref[0]
                image_info = document.extract_image(xref)
                image_bytes = image_info.get("image")
                ext = image_info.get("ext", "png")
                if not image_bytes or len(image_bytes) < 8_000:
                    continue
                image_name = f"{pdf_hash}-page-{page_number:04d}-img-{image_index:02d}.{ext}"
                image_path = Path(image_dir) / image_name
                image_path.write_bytes(image_bytes)
                page_images.append({"path": str(image_path), "page_number": page_number, "ext": ext})
            except Exception:
                continue

        batch_records.append(
            {
                "page_number": page_number,
                "source_file": pdf_name,
                "text": full_text,
                "blocks": text_blocks + table_like_blocks,
                "top_lines": top_lines,
                "bottom_lines": bottom_lines,
                "candidate_lines": candidate_lines,
                "heading_candidates": heading_candidates,
                "images": page_images,
                "is_text_page": len(_normalize_text(full_text)) >= 50,
            }
        )

    document.close()
    return batch_records


def _detect_repeated_margin_lines(raw_pages: Sequence[Dict]) -> set[str]:
    top_counter: Counter = Counter()
    bottom_counter: Counter = Counter()
    page_count = max(len(raw_pages), 1)

    for page in raw_pages:
        for line in page.get("top_lines", []):
            cleaned = _clean_line(line)
            if cleaned:
                top_counter[cleaned] += 1
        for line in page.get("bottom_lines", []):
            cleaned = _clean_line(line)
            if cleaned:
                bottom_counter[cleaned] += 1

    threshold = max(3, int(page_count * 0.2))
    return {line for line, count in {**top_counter, **bottom_counter}.items() if count >= threshold}


def _apply_cleaning_to_page(raw_page: Dict, repeated_margin_lines: set[str]) -> PageRecord:
    cleaned_lines: List[str] = []
    for raw_line in raw_page.get("text", "").splitlines():
        line = _clean_line(raw_line)
        if not line or line in repeated_margin_lines:
            continue
        if len(line) < 20:
            continue
        if re.fullmatch(r"(page\s*)?\d+(\s*/\s*\d+)?", line, flags=re.IGNORECASE):
            continue
        cleaned_lines.append(line)

    cleaned_text = _strip_common_noise("\n".join(cleaned_lines))
    section_heading = _extract_heading_from_font_candidates(raw_page.get("heading_candidates", []))
    return PageRecord(
        page_number=raw_page["page_number"],
        source_file=raw_page["source_file"],
        text=cleaned_text,
        section_heading=section_heading,
        blocks=[_strip_common_noise(block) for block in raw_page.get("blocks", []) if _strip_common_noise(block)],
        images=raw_page.get("images", []),
        image_descriptions=[],
        is_text_page=raw_page.get("is_text_page", False) and bool(cleaned_text),
        heading_candidates=list(raw_page.get("heading_candidates", [])),
    )


def extract_and_clean_pdf(
    pdf_path: str,
    *,
    progress_callback: Optional[Any] = None,
    batch_size: int = PAGE_BATCH_SIZE,
) -> List[Dict]:
    """Extract a PDF page by page, clean noise, and add Gemini image descriptions."""
    _ensure_directories()
    pdf_path = str(Path(pdf_path).expanduser().resolve())
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    pdf_hash = _pdf_fingerprint(pdf_path)
    image_dir = DEFAULT_IMAGE_DIR / pdf_hash
    image_dir.mkdir(parents=True, exist_ok=True)

    with fitz.open(pdf_path) as document:
        total_pages = document.page_count

    futures = []
    raw_pages: List[Dict] = []
    max_workers = max(1, min((os.cpu_count() or 2), 4))
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        total_batches = max(1, math.ceil(total_pages / max(batch_size, 1)))
        completed_batches = 0
        for start_page, end_page in _iter_page_batches(total_pages, batch_size):
            futures.append(executor.submit(_extract_page_batch_worker, pdf_path, start_page, end_page, str(image_dir)))

        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Extracting PDF batches"):
            raw_pages.extend(future.result())
            gc.collect()
            completed_batches += 1
            if progress_callback:
                progress_callback(
                    {
                        "stage": "extracting",
                        "progress": min(45, int((completed_batches / total_batches) * 45)),
                        "batch": completed_batches,
                        "total_batches": total_batches,
                    }
                )

    raw_pages.sort(key=lambda page: page["page_number"])
    repeated_margin_lines = _detect_repeated_margin_lines(raw_pages)
    cleaned_pages = [_apply_cleaning_to_page(page, repeated_margin_lines) for page in raw_pages]

    gemini = GeminiImageAnalyzer()
    total_pages_to_analyze = max(1, len(cleaned_pages))
    for index, page in enumerate(
        tqdm(cleaned_pages, desc="Analyzing page images", disable=not gemini.is_available),
        start=1,
    ):
        if not page.images:
            continue
        for image in page.images:
            image_path = image.get("path")
            if image_path and os.path.exists(image_path):
                description = gemini.describe(Path(image_path).read_bytes(), page.page_number, page.source_file)
                if description:
                    page.image_descriptions.append(description)
        if progress_callback and gemini.is_available:
            progress_callback(
                {
                    "stage": "extracting",
                    "progress": min(55, 45 + int((index / total_pages_to_analyze) * 10)),
                    "page": page.page_number,
                }
            )

    filtered_pages = [page for page in cleaned_pages if page.is_text_page or page.image_descriptions]
    return [asdict(page) for page in filtered_pages]


def _prepare_semantic_sections(page: Dict) -> List[Tuple[str, str]]:
    sections: List[Tuple[str, str]] = []
    heading = page.get("section_heading") or "Document Content"
    text = page.get("text", "")
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]

    for paragraph in paragraphs:
        sections.append((heading, paragraph))
    for image_description in page.get("image_descriptions", []):
        sections.append((f"{heading} - visual context", image_description))
    return sections


def _sentence_safe_chunk_splitter():
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError as exc:
        LOGGER.warning(
            "langchain-text-splitters is not installed; using the built-in large-PDF splitter instead: %s",
            exc,
        )

        class FallbackRecursiveSplitter:
            """Small recursive splitter with sentence-boundary cleanup."""

            separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ": ", ", ", " "]

            def split_text(self, text: str) -> List[str]:
                return self._split_recursive(_normalize_text(text), self.separators)

            def _split_recursive(self, text: str, separators: Sequence[str]) -> List[str]:
                if len(text) <= CHUNK_SIZE:
                    return [text] if text else []
                if not separators:
                    return self._split_long_text(text)

                separator = separators[0]
                parts = text.split(separator)
                if len(parts) == 1:
                    return self._split_recursive(text, separators[1:])

                pieces: List[str] = []
                current = ""
                for part in parts:
                    candidate = part if not current else f"{current}{separator}{part}"
                    if len(candidate) <= CHUNK_SIZE:
                        current = candidate
                        continue

                    if current:
                        pieces.extend(self._sentence_safe_piece(current))
                    current = part

                if current:
                    pieces.extend(self._sentence_safe_piece(current))

                if CHUNK_OVERLAP > 0 and len(pieces) > 1:
                    pieces = self._add_overlap(pieces)
                return pieces

            def _split_long_text(self, text: str) -> List[str]:
                pieces = []
                step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
                for start in range(0, len(text), step):
                    pieces.append(text[start:start + CHUNK_SIZE])
                return pieces

            def _sentence_safe_piece(self, text: str) -> List[str]:
                text = _normalize_text(text)
                if len(text) <= CHUNK_SIZE:
                    return [text] if text else []

                sentences = _sentence_split(text)
                if len(sentences) <= 1:
                    return self._split_long_text(text)

                pieces = []
                current = ""
                for sentence in sentences:
                    candidate = sentence if not current else f"{current} {sentence}"
                    if len(candidate) <= CHUNK_SIZE:
                        current = candidate
                        continue
                    if current:
                        pieces.append(current)
                    current = sentence
                if current:
                    pieces.append(current)
                return pieces

            @staticmethod
            def _add_overlap(pieces: List[str]) -> List[str]:
                overlapped = [pieces[0]]
                for piece in pieces[1:]:
                    previous_tail = overlapped[-1][-CHUNK_OVERLAP:].strip()
                    combined = f"{previous_tail} {piece}".strip() if previous_tail else piece
                    overlapped.append(combined[:CHUNK_SIZE])
                return overlapped

        return FallbackRecursiveSplitter()

    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ": ", ", ", " "],
        keep_separator=True,
        length_function=len,
    )


def chunk_document(
    pages: List[Dict],
    *,
    progress_callback: Optional[Any] = None,
) -> List[Dict]:
    """Chunk documents semantically and attach page-level metadata to every chunk."""
    splitter = _sentence_safe_chunk_splitter()
    chunks: List[ChunkRecord] = []
    source_file = Path(pages[0]["source_file"]).name if pages else "document.pdf"
    chunk_index = 0

    total_pages = max(1, len(pages))
    for page_index, page in enumerate(pages, start=1):
        for section_heading, section_text in _prepare_semantic_sections(page):
            if len(section_text.strip()) < MIN_CHUNK_CHARS:
                continue
            for piece in splitter.split_text(section_text):
                piece = _normalize_text(piece)
                if len(piece) < MIN_CHUNK_CHARS:
                    continue
                sentences = _sentence_split(piece)
                piece = " ".join(sentences) if len(sentences) > 1 else piece
                piece = _normalize_text(piece)
                if len(piece) < MIN_CHUNK_CHARS:
                    continue

                chunk_id = f"{_slugify(Path(source_file).stem)}-p{page['page_number']}-c{chunk_index}"
                chunks.append(
                    ChunkRecord(
                        id=chunk_id,
                        text=piece,
                        metadata={
                            "page_number": page["page_number"],
                            "source_file": source_file,
                            "chunk_index": chunk_index,
                            "section_heading": section_heading,
                        },
                    )
                )
                chunk_index += 1
        if progress_callback:
            progress_callback(
                {
                    "stage": "chunking",
                    "progress": min(70, 55 + int((page_index / total_pages) * 15)),
                    "page": page.get("page_number"),
                    "chunks": len(chunks),
                }
            )

    return [{"id": chunk.id, "text": chunk.text, "metadata": chunk.metadata} for chunk in chunks]


def _decorate_chunks_for_document(
    chunks: List[Dict],
    *,
    document_id: Optional[str] = None,
    document_title: Optional[str] = None,
) -> List[Dict]:
    """Attach application document metadata without changing the public chunking API."""
    decorated = []
    normalized_title = (document_title or "").strip()
    for index, chunk in enumerate(chunks):
        metadata = dict(chunk.get("metadata") or {})
        if document_id:
            metadata["document_id"] = document_id
        if normalized_title:
            metadata["source_file"] = normalized_title
            metadata["document_title"] = normalized_title

        chunk_id = chunk["id"]
        if document_id:
            chunk_id = f"{document_id}-{index}"

        decorated.append(
            {
                "id": chunk_id,
                "text": chunk["text"],
                "metadata": metadata,
            }
        )
    return decorated


def _get_chroma_collection(collection_name: str):
    _ensure_directories()
    client = chromadb.PersistentClient(
        path=str(DEFAULT_CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False, allow_reset=False),
    )
    return client.get_or_create_collection(name=_slugify(collection_name), metadata={"hnsw:space": "cosine"})


def _batched(items: Sequence, batch_size: int) -> Generator[Sequence, None, None]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def embed_and_store(
    chunks: List[Dict],
    collection_name: str,
    *,
    progress_callback: Optional[Any] = None,
) -> Dict:
    """Embed chunks in batches of 32 and persist them to Chroma."""
    if not chunks:
        raise ValueError("No chunks were produced for embedding")

    embedder = _get_embedder()
    collection = _get_chroma_collection(collection_name)
    cache = EmbeddingCache()
    sidecar = HybridIndexStore(collection_name)
    model_name = "BAAI/bge-m3"

    records = [ChunkRecord(id=chunk["id"], text=chunk["text"], metadata=chunk["metadata"]) for chunk in chunks]
    sidecar.merge_records(records)

    all_batches = list(_batched(records, EMBED_BATCH_SIZE))
    total_batches = max(1, len(all_batches))
    for batch_index, batch in enumerate(tqdm(all_batches, desc="Embedding chunks"), start=1):
        texts = [record.text for record in batch]
        cache_hits = cache.get_many(texts, model_name)
        missing_texts = [text for text in texts if _chunk_hash(text) not in cache_hits]
        new_vectors: Dict[str, List[float]] = {}

        if missing_texts:
            encoded = embedder.encode(
                missing_texts,
                batch_size=EMBED_BATCH_SIZE,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            for text, vector in zip(missing_texts, encoded):
                new_vectors[_chunk_hash(text)] = vector.tolist()
            cache.set_many(new_vectors, model_name)
            cache_hits.update(new_vectors)

        collection.upsert(
            ids=[record.id for record in batch],
            documents=[record.text for record in batch],
            metadatas=[record.metadata for record in batch],
            embeddings=[cache_hits[_chunk_hash(text)] for text in texts],
        )
        if progress_callback:
            progress_callback(
                {
                    "stage": "embedding",
                    "progress": min(95, 70 + int((batch_index / total_batches) * 25)),
                    "batch": batch_index,
                    "total_batches": total_batches,
                }
            )

    return {"collection_name": _slugify(collection_name), "chunks_indexed": len(records), "storage_path": str(DEFAULT_CHROMA_DIR)}


def hybrid_retrieve(query: str, collection_name: str) -> Dict:
    """Run dense + BM25 retrieval and fuse the rankings with RRF."""
    if not query.strip():
        raise ValueError("Query cannot be empty")

    embedder = _get_embedder()
    reranker = _get_reranker()
    collection = _get_chroma_collection(collection_name)
    sidecar = HybridIndexStore(collection_name)
    bm25, bm25_records = sidecar.load_or_build_bm25()

    query_text = f"{QUERY_EMBED_PREFIX}{query.strip()}"
    query_vector = embedder.encode(
        [query_text],
        batch_size=1,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )[0].tolist()
    dense = collection.query(
        query_embeddings=[query_vector],
        n_results=max(RETRIEVE_TOP_K * 2, 12),
        include=["documents", "metadatas", "distances"],
    )

    dense_candidates: Dict[str, Dict] = {}
    dense_docs = dense.get("documents", [[]])[0]
    dense_meta = dense.get("metadatas", [[]])[0]
    dense_distances = dense.get("distances", [[]])[0]
    for rank, (document_text, metadata, distance) in enumerate(zip(dense_docs, dense_meta, dense_distances), start=1):
        record_id = f"{_slugify(Path(metadata['source_file']).stem)}-p{metadata['page_number']}-c{metadata['chunk_index']}"
        dense_candidates[record_id] = {
            "id": record_id,
            "text": document_text,
            "metadata": metadata,
            "dense_rank": rank,
            "dense_score": max(0.0, 1.0 - float(distance)),
        }

    bm25_scores = bm25.get_scores(_tokenize_for_bm25(query))
    bm25_ranked = sorted(enumerate(bm25_scores), key=lambda item: item[1], reverse=True)[: max(RETRIEVE_TOP_K * 2, 12)]
    fused: Dict[str, Dict] = defaultdict(lambda: {"rrf_score": 0.0})

    for record_id, candidate in dense_candidates.items():
        fused[record_id].update(candidate)
        fused[record_id]["rrf_score"] += 1.0 / (RRF_K + candidate["dense_rank"])

    for rank, (index, score) in enumerate(bm25_ranked, start=1):
        record = bm25_records[index]
        record_id = record["id"]
        fused[record_id].update(
            {
                "id": record_id,
                "text": record["text"],
                "metadata": record["metadata"],
                "bm25_rank": rank,
                "bm25_score": float(score),
            }
        )
        fused[record_id]["rrf_score"] += 1.0 / (RRF_K + rank)

    fused_ranked = sorted(fused.values(), key=lambda item: item.get("rrf_score", 0.0), reverse=True)[:RETRIEVE_TOP_K]
    if not fused_ranked:
        return {"results": [], "confidence": 0.0}

    rerank_scores = reranker.predict([(query, candidate["text"]) for candidate in fused_ranked])
    reranked = []
    for candidate, score in zip(fused_ranked, rerank_scores):
        candidate["rerank_score"] = float(score)
        candidate["confidence_score"] = _sigmoid(float(score))
        reranked.append(candidate)

    reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    final_results = reranked[:RERANK_TOP_K]
    confidence = final_results[0]["confidence_score"] if final_results else 0.0
    return {"results": final_results, "confidence": confidence}


def collection_has_data(collection_name: str) -> bool:
    """Check whether a persisted large-PDF collection has chunks on disk."""
    try:
        sidecar = HybridIndexStore(collection_name)
        return bool(sidecar.load_records())
    except Exception:
        return False


def preview_document_chunks(collection_name: str, document_id: str, limit: int = 8) -> List[Dict]:
    """Return lightweight chunk previews for a single large-PDF document."""
    sidecar = HybridIndexStore(collection_name)
    records = sidecar.load_records()
    preview_limit = max(1, min(limit, 12))
    rows = []
    for record in records:
        metadata = record.get("metadata") or {}
        if metadata.get("document_id") != document_id:
            continue
        rows.append(
            {
                "chunk_index": metadata.get("chunk_index", 0),
                "chunk_text": record.get("text", "")[:320].strip(),
                "metadata": metadata,
            }
        )
    rows.sort(key=lambda item: item.get("chunk_index", 0))
    return rows[:preview_limit]


def delete_document(collection_name: str, document_id: str) -> bool:
    """Delete a large-PDF document from Chroma and rebuild the BM25 sidecar."""
    sidecar = HybridIndexStore(collection_name)
    records = sidecar.load_records()
    remaining = [record for record in records if (record.get("metadata") or {}).get("document_id") != document_id]
    deleted = len(remaining) != len(records)

    if deleted:
        chunk_records = [
            ChunkRecord(id=record["id"], text=record["text"], metadata=record.get("metadata") or {})
            for record in remaining
        ]
        sidecar.write_records(chunk_records)

    try:
        collection = _get_chroma_collection(collection_name)
        payload = collection.get(where={"document_id": document_id})
        if payload and payload.get("ids"):
            collection.delete(ids=payload["ids"])
            deleted = True
    except Exception:
        pass

    return deleted


def _build_sources_footer(results: Sequence[Dict]) -> str:
    lines = ["Sources:"]
    for index, item in enumerate(results, start=1):
        metadata = item["metadata"]
        lines.append(
            f"[{index}] {metadata['source_file']} | page {metadata['page_number']} | "
            f"chunk {metadata['chunk_index']} | {metadata.get('section_heading', 'Document Content')}"
        )
    return "\n".join(lines)


def _normalize_for_verification(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _claim_is_grounded(claim: str, contexts: Sequence[str]) -> bool:
    normalized_claim = _normalize_for_verification(claim)
    if len(normalized_claim) < 30:
        return True
    if any(normalized_claim in _normalize_for_verification(context) for context in contexts):
        return True

    claim_words = normalized_claim.split()
    if len(claim_words) < 6:
        return False

    claim_ngrams = {" ".join(claim_words[i : i + 6]) for i in range(len(claim_words) - 5)}
    for context in contexts:
        normalized_context = _normalize_for_verification(context)
        if any(ngram in normalized_context for ngram in claim_ngrams):
            return True
    return False


def _verify_answer(answer: str, retrieved_results: Sequence[Dict]) -> bool:
    contexts = [result["text"] for result in retrieved_results]
    candidate_claims = [line.strip("- ").strip() for line in re.split(r"\n+|(?<=[.!?])\s+", answer) if line.strip()]
    checked = 0
    grounded = 0
    for claim in candidate_claims:
        lowered = claim.lower()
        if lowered.startswith("sources:") or lowered.startswith("["):
            continue
        if len(claim) < 24:
            continue
        checked += 1
        if _claim_is_grounded(claim, contexts):
            grounded += 1
    if checked == 0:
        return True
    return grounded / checked >= 0.6


def _build_extractive_fallback(query: str, retrieved_results: Sequence[Dict]) -> str:
    query_terms = set(_tokenize_for_bm25(query))
    scored_sentences: List[Tuple[int, str, Dict]] = []
    for result in retrieved_results:
        for sentence in _sentence_split(result["text"]):
            sentence_terms = set(_tokenize_for_bm25(sentence))
            overlap = len(query_terms & sentence_terms)
            if overlap == 0 or len(sentence) < 40:
                continue
            scored_sentences.append((overlap, sentence, result["metadata"]))

    scored_sentences.sort(key=lambda item: item[0], reverse=True)
    picked = scored_sentences[:3]
    if not picked:
        return "Not enough information found"

    lines: List[str] = []
    for index, (_, sentence, metadata) in enumerate(picked, start=1):
        lines.append(f"{sentence} [{index}]")
        lines.append(
            f"[{index}] {metadata['source_file']} | page {metadata['page_number']} | chunk {metadata['chunk_index']}"
        )
    return "\n".join(lines)


def answer_question(query: str, collection_name: str) -> str:
    """Answer a question using only the reranked chunks."""
    retrieval = hybrid_retrieve(query, collection_name)
    retrieved_results = retrieval["results"]
    confidence = retrieval["confidence"]

    if not retrieved_results or confidence < 0.5:
        return "Not enough information found"

    groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required for answer generation")

    context_blocks = []
    for index, result in enumerate(retrieved_results, start=1):
        metadata = result["metadata"]
        context_blocks.append(
            "\n".join(
                [
                    f"[Chunk {index}]",
                    f"Source file: {metadata['source_file']}",
                    f"Page number: {metadata['page_number']}",
                    f"Chunk index: {metadata['chunk_index']}",
                    f"Section heading: {metadata.get('section_heading', 'Document Content')}",
                    f"Content: {result['text']}",
                ]
            )
        )

    messages = [
        {
            "role": "system",
            "content": (
                "Answer ONLY from the provided context. "
                "If the answer is not in the context, say so explicitly. "
                "Never invent facts."
            ),
        },
        {
            "role": "user",
            "content": (
                "Use only the chunks below.\n\n"
                f"{chr(10).join(context_blocks)}\n\n"
                f"Question: {query}\n\n"
                "Write a clear answer with page-number citations in the prose when relevant. "
                "Keep the answer concise and factual."
            ),
        },
    ]

    client = OpenAI(api_key=groq_api_key, base_url=GROQ_BASE_URL)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=700,
    )
    answer = response.choices[0].message.content.strip()

    if not _verify_answer(answer, retrieved_results):
        answer = _build_extractive_fallback(query, retrieved_results)
        if answer == "Not enough information found":
            return answer

    return f"{answer}\n\n{_build_sources_footer(retrieved_results)}"


def answer_question_payload(query: str, collection_name: str) -> Dict:
    """Return an API-friendly answer payload without duplicating the sources footer in the body."""
    retrieval = hybrid_retrieve(query, collection_name)
    retrieved_results = retrieval["results"]
    confidence = retrieval["confidence"]

    if not retrieved_results or confidence < 0.5:
        return {"response": "Not enough information found", "sources": [], "confidence": confidence}

    groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required for answer generation")

    context_blocks = []
    for index, result in enumerate(retrieved_results, start=1):
        metadata = result["metadata"]
        context_blocks.append(
            "\n".join(
                [
                    f"[Chunk {index}]",
                    f"Source file: {metadata['source_file']}",
                    f"Page number: {metadata['page_number']}",
                    f"Chunk index: {metadata['chunk_index']}",
                    f"Section heading: {metadata.get('section_heading', 'Document Content')}",
                    f"Content: {result['text']}",
                ]
            )
        )

    client = OpenAI(api_key=groq_api_key, base_url=GROQ_BASE_URL)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer ONLY from the provided context. "
                    "If the answer is not in the context, say so explicitly. "
                    "Never invent facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Use only the chunks below.\n\n"
                    f"{chr(10).join(context_blocks)}\n\n"
                    f"Question: {query}\n\n"
                    "Write a clear answer with page-number citations in the prose when relevant. "
                    "Keep the answer concise and factual."
                ),
            },
        ],
        temperature=0.1,
        max_tokens=700,
    )
    answer = response.choices[0].message.content.strip()
    if not _verify_answer(answer, retrieved_results):
        answer = _build_extractive_fallback(query, retrieved_results)

    sources = []
    for result in retrieved_results:
        metadata = result["metadata"]
        sources.append(
            {
                "document_id": metadata.get("document_id") or result["id"],
                "document_title": metadata.get("document_title") or metadata.get("source_file", "Large PDF"),
                "chunk_text": result["text"],
                "relevance_score": float(result.get("confidence_score") or result.get("dense_score") or 0.0),
                "page_number": metadata.get("page_number"),
                "chunk_index": metadata.get("chunk_index"),
                "section_heading": metadata.get("section_heading"),
            }
        )

    return {"response": answer, "sources": sources, "confidence": confidence}


def index_pdf_document(
    pdf_path: str,
    collection_name: str,
    *,
    document_id: Optional[str] = None,
    document_title: Optional[str] = None,
) -> Dict:
    """Index a PDF into the shared large-PDF collection with app metadata attached."""
    pages = extract_and_clean_pdf(pdf_path)
    chunks = chunk_document(pages)
    decorated_chunks = _decorate_chunks_for_document(
        chunks,
        document_id=document_id,
        document_title=document_title,
    )
    return embed_and_store(decorated_chunks, collection_name)


def job_collection_name(job_id: str) -> str:
    """Build a stable per-job collection name."""
    return _slugify(f"document-job-{job_id}")


def _index_pdf(pdf_path: str, collection_name: str) -> Dict:
    return index_pdf_document(pdf_path, collection_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Large-PDF hybrid RAG CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Index a PDF into a collection")
    index_parser.add_argument("--pdf", required=True, help="Path to the PDF file")
    index_parser.add_argument("--collection", required=True, help="Collection name")

    ask_parser = subparsers.add_parser("ask", help="Ask a question against an indexed collection")
    ask_parser.add_argument("--collection", required=True, help="Collection name")
    ask_parser.add_argument("--query", required=True, help="Question to ask")

    args = parser.parse_args()
    if args.command == "index":
        print(json.dumps(_index_pdf(args.pdf, args.collection), indent=2))
        return
    if args.command == "ask":
        print(answer_question(args.query, args.collection))
        return


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
