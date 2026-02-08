import os

from langchain_community.document_loaders import (
    PyMuPDFLoader,
    TextLoader,
    Docx2txtLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings

# ---------- Paths ----------
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data_documents")
DB_DIR = os.path.join(BASE_DIR, "chroma_db")

# ---------- Embeddings ----------
embeddings = OllamaEmbeddings(
    model="nomic-embed-text"
)

# ---------- Load documents ----------
documents = []

for filename in os.listdir(DATA_DIR):
    path = os.path.join(DATA_DIR, filename)

    if filename.lower().endswith(".pdf"):
        loader = PyMuPDFLoader(path)
        pages = loader.load()

        for p in pages:
            if p.page_content and len(p.page_content.strip()) > 50:
                documents.append(p)

    elif filename.lower().endswith(".txt"):
        loader = TextLoader(path, encoding="utf-8")
        documents.extend(loader.load())

    elif filename.lower().endswith(".docx"):
        loader = Docx2txtLoader(path)
        documents.extend(loader.load())

    else:
        print(f"Skipping unsupported file: {filename}")

print(f"Loaded {len(documents)} pages with usable text")

# ---------- Safety check ----------
if not documents:
    raise RuntimeError(
        "No usable text found in documents. "
        "PDFs may be scanned or text extraction failed."
    )

# ---------- Split documents ----------
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=150,
    separators=["\n\n", "\n", " ", ""],
)

chunks = text_splitter.split_documents(documents)

if not chunks:
    raise RuntimeError(
        "Documents loaded but could not be split into chunks."
    )

print(f"Split into {len(chunks)} chunks")

# ---------- Store in Chroma ----------
vectordb = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory=DB_DIR,
)

vectordb.persist()

print("✅ Ingestion complete. Vector DB updated successfully.")
