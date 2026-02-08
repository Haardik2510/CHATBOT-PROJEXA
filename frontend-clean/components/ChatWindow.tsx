"use client";

import { useEffect, useRef, useState } from "react";

type Message = {
  role: "user" | "assistant";
  content: string;
  status?: "thinking" | "typing" | "done";
};

export default function ChatWindow({
  messages,
}: {
  messages: Message[];
}) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [animatedText, setAnimatedText] = useState("");

  const lastMessage = messages[messages.length - 1];

  // Gemini-style typing animation
  useEffect(() => {
    if (
      !lastMessage ||
      lastMessage.role !== "assistant" ||
      lastMessage.status !== "typing"
    ) {
      setAnimatedText("");
      return;
    }

    const safeText = lastMessage.content || "";
    const words = safeText.split(" ");
    let index = 0;

    setAnimatedText("");

    const interval = setInterval(() => {
      setAnimatedText((prev) =>
        prev ? prev + " " + words[index] : words[index]
      );
      index++;

      if (index >= words.length) {
        clearInterval(interval);
      }
    }, 40); // 👈 controls typing speed

    return () => clearInterval(interval);
  }, [lastMessage]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, animatedText]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
      {messages.map((msg, i) => {
        const isUser = msg.role === "user";
        const isLast = i === messages.length - 1;

        return (
          <div
            key={i}
            className={`flex ${
              isUser ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`max-w-[70%] rounded-2xl px-4 py-3 text-sm leading-relaxed
                ${
                  isUser
                    ? "bg-blue-600 text-white"
                    : "bg-zinc-800 text-zinc-100"
                }`}
            >
              {/* THINKING STATE */}
              {msg.role === "assistant" && msg.status === "thinking" && (
                <span className="thinking-dots">
                <span>.</span>
               <span>.</span>
                <span>.</span>
                </span>

              )}

              {/* TYPING STATE */}
              {msg.role === "assistant" &&
                msg.status === "typing" &&
                isLast && <span>{animatedText}</span>}

              {/* DONE STATE */}
              {(!msg.status || msg.status === "done") &&
                msg.content}
            </div>
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
