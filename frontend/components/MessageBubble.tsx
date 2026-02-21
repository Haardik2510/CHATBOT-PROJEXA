"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Volume2 } from "lucide-react";

type Message = {
  role: "user" | "assistant";
  content: string;
  status?: "thinking" | "done";
};

export default function MessageBubble({
  message,
}: {
  message: Message;
}) {
  const isUser = message.role === "user";
  const [displayText, setDisplayText] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setDisplayText(message.content);
  }, [message]);

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  const speakText = () => {
    if (!("speechSynthesis" in window)) return;

    const utterance = new SpeechSynthesisUtterance(message.content);
    utterance.lang = "en-US";
    utterance.rate = 1;
    utterance.pitch = 1;

    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  };

  return (
    <div
      className={`flex ${
        isUser ? "justify-end" : "justify-start"
      } animate-fadeIn group`}
    >
      <div
        className={`relative max-w-[65%] rounded-2xl px-5 py-3 text-sm shadow-xl ${
          isUser
            ? "bg-indigo-600 text-white"
            : "glass text-slate-100"
        }`}
      >
        {/* Hover Toolbar (Only for Assistant) */}
        {!isUser && (
          <div className="absolute -top-8 right-2 opacity-0 group-hover:opacity-100 transition flex gap-2 bg-black/60 backdrop-blur-md px-2 py-1 rounded-lg shadow-lg">
            
            {/* Copy */}
            <button
              onClick={handleCopy}
              className="hover:text-indigo-400 transition"
              title="Copy"
            >
              <Copy size={14} />
            </button>

            {/* Speaker */}
            <button
              onClick={speakText}
              className="hover:text-indigo-400 transition"
              title="Listen"
            >
              <Volume2 size={14} />
            </button>

          </div>
        )}

        {isUser ? (
          displayText
        ) : (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ inline, children }) {
                return inline ? (
                  <code className="bg-slate-800 px-1 rounded text-indigo-300">
                    {children}
                  </code>
                ) : (
                  <pre className="bg-black/60 p-3 rounded-lg overflow-x-auto">
                    <code className="text-green-400 text-xs">
                      {children}
                    </code>
                  </pre>
                );
              },
            }}
          >
            {displayText}
          </ReactMarkdown>
        )}
      </div>
    </div>
  );
}