from langchain_ollama import OllamaLLM

# ⚡ FAST CONFIG
llm = OllamaLLM(
    model="phi3",
    temperature=0.3,
    num_predict=200,     # LIMIT OUTPUT TOKENS
    top_p=0.9
)

def quick_reply(message: str) -> str:
    return llm.invoke(
        f"You are a friendly assistant. Reply briefly to: {message}"
    )

def generate_answer(question: str, context: str) -> str:
    prompt = f"""
You are a helpful AI assistant for KR Mangalam University.
Answer clearly and concisely.
If the answer is not in the context, say you do not know.

Context:
{context}

Question:
{question}

Answer:
"""
    return llm.invoke(prompt)
