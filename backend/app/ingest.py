import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import Chroma

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "data_documents")
DB_DIR = os.path.join(BASE_DIR, "chroma_db")

def ingest():
    documents = []

    for file in os.listdir(DOCS_DIR):
        if file.lower().endswith(".pdf"):
            loader = PyPDFLoader(os.path.join(DOCS_DIR, file))
            documents.extend(loader.load())

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50
    )

    chunks = splitter.split_documents(documents)
    chunks = chunks[:200]  # HARD LIMIT → prevents freezing

    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=DB_DIR
    )

    print(f"[OK] Ingested {len(chunks)} chunks")

if __name__ == "__main__":
    ingest()
