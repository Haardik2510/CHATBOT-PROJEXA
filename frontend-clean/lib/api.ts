export async function sendMessage(message: string) {
  const res = await fetch("http://127.0.0.1:8000/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });

  if (!res.ok) {
    throw new Error("Backend error");
  }

  const data = await res.json();

  return {
    answer:
      typeof data.answer === "string"
        ? data.answer
        : "I do not have this information in my knowledge base.",
  };
}
