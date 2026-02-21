"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, Paperclip, Send } from "lucide-react";

export default function ChatInput({
  onSend,
}: {
  onSend: (text: string, file?: File) => void;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [listening, setListening] = useState(false);

  const fileRef = useRef<HTMLInputElement | null>(null);
  const recognitionRef = useRef<any>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  /* -----------------------------
     Clipboard Image Paste Support
  ----------------------------- */
  useEffect(() => {
    const handlePaste = (event: ClipboardEvent) => {
      if (!event.clipboardData) return;

      const items = event.clipboardData.items;

      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.type.startsWith("image/")) {
          const blob = item.getAsFile();
          if (blob) setFile(blob);
        }
      }
    };

    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  }, []);

  /* -----------------------------
     Speech Recognition
  ----------------------------- */
  const startListening = () => {
    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      alert("Voice recognition not supported in this browser.");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;

    recognition.onstart = () => setListening(true);

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setText(transcript);
      setListening(false);
    };

    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    recognition.start();
  };

  /* -----------------------------
     Send Message
  ----------------------------- */
  const send = () => {
    if (!text.trim() && !file) return;

    onSend(text, file || undefined);

    setText("");
    setFile(null);

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  return (
    <div className="p-6 border-t border-slate-800">
      <div className="glass max-w-4xl mx-auto flex flex-col gap-3 px-5 py-4 rounded-2xl shadow-xl focus-within:ring-2 focus-within:ring-indigo-500/40 transition">

        {/* File Preview */}
        {file && (
          <div className="flex items-center justify-between bg-slate-800/60 rounded-lg px-4 py-2 text-sm">
            <span className="truncate">📎 {file.name || "Pasted Image"}</span>
            <button
              onClick={() => setFile(null)}
              className="text-red-400 hover:text-red-300"
            >
              ✕
            </button>
          </div>
        )}

        <div className="flex items-center gap-4">

          {/* Attach File */}
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="text-slate-400 hover:text-white transition"
          >
            <Paperclip size={18} />
          </button>

          <input
            ref={fileRef}
            type="file"
            tabIndex={-1}
            className="hidden"
            accept="image/*,.pdf,.doc,.docx"
            onChange={(e) =>
              e.target.files && setFile(e.target.files[0])
            }
          />

          {/* Textarea */}
          <textarea
            ref={textareaRef}
            rows={1}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              const target = e.target as HTMLTextAreaElement;
              target.style.height = "auto";
              target.style.height = target.scrollHeight + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Ask something..."
            className="flex-1 resize-none bg-transparent outline-none text-sm text-white placeholder:text-slate-500 max-h-40 overflow-y-auto"
          />

          {/* Mic Button */}
          <button
            type="button"
            onClick={startListening}
            className={`transition-all ${
              listening
                ? "text-indigo-400 animate-pulse"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Mic size={18} />
          </button>

          {/* Send Button */}
          <button
            onClick={send}
            className="bg-indigo-600 hover:bg-indigo-500 active:scale-95 transition-all duration-150 px-4 py-2 rounded-full text-sm text-white shadow-lg shadow-indigo-500/20"
          >
            <Send size={16} />
          </button>

        </div>
      </div>
    </div>
  );
}