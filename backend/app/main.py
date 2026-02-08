from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import ChatRequest, ChatResponse
from app.rag import retrieve_context
from app.llm import cached_generate_answer

app = FastAPI(title="KRMU AI Assistant Backend")

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Health ----------
@app.get("/")
def health():
    return {"status": "Backend running"}

# ---------- Chat ----------
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    print(f"[CHAT] Question: {req.message}")

    context = retrieve_context(req.message)

    if not context:
        print("[CHAT] No relevant context found")

    answer = cached_generate_answer(req.message, context)

    return {"answer": answer}
