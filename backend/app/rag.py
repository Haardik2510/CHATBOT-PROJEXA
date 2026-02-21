import os
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DB_DIR = os.path.join(BASE_DIR, "chroma_db")

embeddings = OllamaEmbeddings(model="nomic-embed-text")

# ✅ LOAD ONCE
db = Chroma(
    persist_directory=DB_DIR,
    embedding_function=embeddings
)

def retrieve_context(query: str) -> str:
    docs = db.similarity_search(query, k=3)
    return "\n\n".join(d.page_content for d in docs)
