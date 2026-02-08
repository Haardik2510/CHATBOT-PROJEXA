"use client";

import { useState } from "react";
import ChatWindow from "@/components/ChatWindow";
import ChatInput from "@/components/ChatInput";
import { sendMessage } from "@/lib/api";

type Message = {
  role: "user" | "assistant";
  content: string;
  status?: "thinking" | "typing" | "done";
};

export default function Page() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "KR Mangalam University AI Assistant ready.",
      status: "done",
    },
  ]);

  const handleSend = async (text: string) => {
    // 1️⃣ User message + thinking placeholder
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      {
        role: "assistant",
        content: "",
        status: "thinking",
      },
    ]);

    try {
      const res = await sendMessage(text);

      // 2️⃣ Switch to typing state
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: res.answer,
          status: "typing",
        };
        return updated;
      });

      // 3️⃣ After typing completes → mark done
      setTimeout(() => {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            status: "done",
          };
          return updated;
        });
      }, Math.min(2000, res.answer.length * 40));
    } catch {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content:
            "⚠️ I ran into a problem while responding. Please try again.",
          status: "done",
        };
        return updated;
      });
    }
  };

  return (
    <main className="flex h-screen flex-col bg-zinc-950 text-zinc-200">
      <header className="border-b border-white/10 bg-zinc-900 px-6 py-4">
        <h1 className="text-sm font-semibold text-white">
          KR Mangalam University AI Assistant
        </h1>
        <p className="text-xs text-zinc-400">
          Academic Intelligence System
        </p>
      </header>

      <ChatWindow messages={messages} />
      <ChatInput onSend={handleSend} />
    </main>
  );
}
