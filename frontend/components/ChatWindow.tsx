"use client";

import { useEffect, useRef, useState } from "react";
import MessageBubble from "./MessageBubble";
import TypingIndicator from "./TypingIndicator";

export default function ChatWindow({ messages }: any) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const handleScroll = () => {
      if (!containerRef.current) return;
      setScrolled(containerRef.current.scrollTop > 10);
    };

    containerRef.current?.addEventListener("scroll", handleScroll);
    return () =>
      containerRef.current?.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div className="flex-1 relative overflow-hidden animate-fadeIn">
      {/* Scroll Shadow */}
      <div
        className={`absolute top-0 left-0 right-0 h-8 pointer-events-none transition-opacity duration-300
        bg-gradient-to-b from-black/40 to-transparent ${
          scrolled ? "opacity-100" : "opacity-0"
        }`}
      />

      <div
        ref={containerRef}
        className="h-full overflow-y-auto"
      >
        <div className="max-w-4xl mx-auto w-full px-6 py-10 space-y-8">
          {messages.map((msg: any, i: number) =>
            msg.status === "thinking" ? (
              <TypingIndicator key={i} />
            ) : (
              <MessageBubble key={i} message={msg} />
            )
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}