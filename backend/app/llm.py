from functools import lru_cache
from langchain_ollama import OllamaLLM

# ---------- LLM ----------
llm = OllamaLLM(
    model="phi3",        # ✅ Best for 8 GB RAM
    temperature=0.1,     # ✅ Factual, low hallucination
)

# ---------- Answer generation ----------
def generate_answer(question: str, context: str) -> str:
    """
    Generate a concise, grounded answer using retrieved context only.
    """

    # 🔴 Hard guard: no context, no answer
    if not context or len(context.strip()) < 100:
        return "I do not have this information in my knowledge base."

    prompt = f"""
You are KRMU AI Assistant for KR Mangalam University.

STRICT RULES:
- Use ONLY the information present in the context.
- Do NOT add facts, assumptions, or general knowledge.
- If the context does not contain the answer, respond EXACTLY with:
  "I do not have this information in my knowledge base."
- Keep the answer concise (3–6 sentences max).
- Use bullet points ONLY if it improves clarity.
- Do NOT mention the word "context" in your answer.

Context:
{context}

Question:
{question}

Answer:
"""

    response = llm.invoke(prompt)

    # 🔴 Safety cleanup
    answer = response.strip()

    if not answer:
        return "I do not have this information in my knowledge base."

    return answer


# ---------- Cache (critical for speed & UX) ----------
@lru_cache(maxsize=128)
def cached_generate_answer(question: str, context: str) -> str:
    return generate_answer(question, context)
