from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import ChatRequest, ChatResponse
from app.rag import retrieve_context
from app.llm import generate_answer, quick_reply

app = FastAPI(title="KRMU AI Assistant")

# ✅ CORS (keep this always)
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

# ✅ Health route (prevents 404 on root)
@app.get("/")
def health():
    return {"status": "Backend running"}

SMALL_TALK = {
    "hi", "hello", "hey", "thanks", "thank you",
    "how are you", "ok", "okay"
}

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    user_msg = req.message.strip().lower()

    # ⚡ FAST PATH (NO RAG)
    if user_msg in SMALL_TALK or len(user_msg) < 6:
        return {"answer": quick_reply(req.message)}

    # 🧠 RAG PATH
    context = retrieve_context(req.message)
    answer = generate_answer(req.message, context)

    return {
        "answer": answer or
        "I do not have this information in my knowledge base."
    }
