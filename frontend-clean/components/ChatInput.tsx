"use client";

import { useState } from "react";

export default function ChatInput({
  onSend,
}: {
  onSend: (text: string) => void;
}) {
  const [input, setInput] = useState("");

  const send = () => {
    if (!input.trim()) return;
    onSend(input);
    setInput("");
  };

  return (
    <div className="border-t border-white/10 bg-zinc-900 px-3 py-4">
      <div className="mx-auto flex max-w-3xl items-center gap-3 rounded-full border border-white/10 bg-zinc-800 px-4 py-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask anything about KR Mangalam University…"
          className="flex-1 bg-transparent text-sm text-white outline-none"
        />
        <button
          onClick={send}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-black"
        >
          ▶
        </button>
      </div>
    </div>
  );
}
