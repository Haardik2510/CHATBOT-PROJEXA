import os
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings

# ---------- Paths ----------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DB_DIR = os.path.join(BASE_DIR, "chroma_db")

# ---------- Load embeddings once ----------
_embeddings = OllamaEmbeddings(
    model="nomic-embed-text"
)

# ---------- Load vector DB once ----------
_vectordb = Chroma(
    persist_directory=DB_DIR,
    embedding_function=_embeddings
)

# ---------- Retrieval ----------
def retrieve_context(query: str, k: int = 4, max_chars: int = 1500) -> str:
    """
    High-accuracy context retrieval tuned for low-RAM + phi3.

    - Filters junk chunks
    - Deduplicates overlapping content
    - Caps total context length
    """

    docs = _vectordb.similarity_search(query, k=k)

    if not docs:
        return ""

    seen = set()
    selected_chunks = []
    total_length = 0

    for doc in docs:
        text = (doc.page_content or "").strip()

        # 🔴 Skip junk / very short chunks
        if len(text) < 80:
            continue

        # 🔴 Deduplicate
        key = text[:120]
        if key in seen:
            continue
        seen.add(key)

        # 🔴 Respect context length cap
        if total_length + len(text) > max_chars:
            break

        selected_chunks.append(text)
        total_length += len(text)

    return "\n\n".join(selected_chunks)
