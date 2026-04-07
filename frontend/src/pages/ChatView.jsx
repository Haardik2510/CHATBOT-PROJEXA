import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import axios from "axios";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { ScrollArea } from "../components/ui/scroll-area";
import {
  Mic,
  MicOff,
  Send,
  Volume2,
  VolumeX,
  Copy,
  Check,
  Share2,
  FileText,
  Sparkles,
  RotateCcw,
  BookOpen,
  ScanSearch,
  FileStack,
} from "lucide-react";

import { API } from "../lib/api";

const DATABASE_MODE = "database";

const shortcuts = [
  { label: "Smart Citation", icon: FileText },
  { label: "Instant Abstract", icon: ScanSearch },
  { label: "Source Stack", icon: FileStack },
];

const suggestions = [
  "Tell me about K.R. Mangalam University campus facilities",
  "What are the admission requirements for B.Tech?",
  "Summarize hostel facilities and student life",
];

const getDatabaseConfidence = (sources = []) => {
  const bestScore = Math.max(...sources.map((source) => Number(source?.relevance_score || 0)), 0);
  if (bestScore >= 0.82) {
    return { label: "High confidence", className: "bg-emerald-500/12 text-emerald-700 border border-emerald-500/20" };
  }
  if (bestScore >= 0.62) {
    return { label: "Medium confidence", className: "bg-[#6294ff]/12 text-[#24428a] border border-[#6294ff]/20" };
  }
  return { label: "Low confidence", className: "bg-[#b6171e]/8 text-[#b6171e] border border-[#b6171e]/15" };
};

const shouldInlineCite = (line) => {
  const normalized = (line || "").trim();
  if (!normalized) return false;
  return (
    !/^source:/i.test(normalized) &&
    !/^additional source:/i.test(normalized) &&
    !/^if you want/i.test(normalized) &&
    !/^what i could not verify/i.test(normalized)
  );
};

export default function ChatView() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const messagesEndRef = useRef(null);
  const recognitionRef = useRef(null);
  const synthRef = useRef(window.speechSynthesis);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      recognitionRef.current = new SpeechRecognition();
      recognitionRef.current.continuous = false;
      recognitionRef.current.interimResults = true;
      recognitionRef.current.lang = "en-US";

      recognitionRef.current.onresult = (event) => {
        const transcript = Array.from(event.results)
          .map((result) => result[0].transcript)
          .join("");
        setInput(transcript);
      };

      recognitionRef.current.onend = () => {
        setIsRecording(false);
      };

      recognitionRef.current.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        setIsRecording(false);
        if (event.error === "not-allowed") {
          toast.error("Microphone access denied. Please enable it in your browser settings.");
        }
      };
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }
    };
  }, []);

  const toggleRecording = () => {
    if (!recognitionRef.current) {
      toast.error("Speech recognition not supported in this browser");
      return;
    }

    if (isRecording) {
      recognitionRef.current.stop();
      setIsRecording(false);
      return;
    }

    setInput("");
    recognitionRef.current.start();
    setIsRecording(true);
  };

  const speakText = (text) => {
    if (isSpeaking) {
      synthRef.current.cancel();
      setIsSpeaking(false);
      return;
    }

    const cleanText = String(text || "").replace(/\*\*/g, "").replace(/\*/g, "").replace(/_/g, "");
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);

    setIsSpeaking(true);
    synthRef.current.speak(utterance);
  };

  const buildFriendlyChatError = (error) => {
    const status = error?.response?.status;
    const detail = error?.response?.data?.detail;

    if (detail && typeof detail === "string") {
      return detail;
    }

    if (status === 401) {
      return "Your session has expired. Please sign in again to continue chatting.";
    }

    if (status === 403) {
      return "Your account does not have permission to use this action.";
    }

    if (status >= 500) {
      return "I’m having trouble reaching the knowledge services right now. Please try again in a moment.";
    }

    return "I couldn’t answer that just now. Please try again, or rephrase your question.";
  };

  const copyResponse = async (text, index) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      toast.success("Response copied");
      window.setTimeout(() => setCopiedIndex(null), 1800);
    } catch (error) {
      console.error("Copy error:", error);
      toast.error("Could not copy the response");
    }
  };

  const shareResponse = async (text) => {
    try {
      if (navigator.share) {
        await navigator.share({
          title: "Scholar Pulse Response",
          text,
        });
        return;
      }

      await navigator.clipboard.writeText(text);
      toast.success("Sharing is not available here, so the response was copied instead");
    } catch (error) {
      if (error?.name !== "AbortError") {
        console.error("Share error:", error);
        toast.error("Could not share the response");
      }
    }
  };

  const sendMessage = async (voiceInput = false) => {
    if (!input.trim() || isLoading) return;

    const userMessage = {
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString(),
      answerMode: DATABASE_MODE,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await axios.post(`${API}/chat`, {
        message: userMessage.content,
        session_id: sessionId,
        voice_input: voiceInput,
        answer_mode: DATABASE_MODE,
      });

      const { response: aiResponse, sources, images, session_id } = response.data;

      if (!sessionId) {
        setSessionId(session_id);
      }

      const assistantMessage = {
        role: "assistant",
        content: aiResponse,
        sources: sources || [],
        images: images || [],
        timestamp: new Date().toISOString(),
        answerMode: DATABASE_MODE,
      };

      setMessages((prev) => [...prev, assistantMessage]);

      if (voiceInput && aiResponse) {
        speakText(aiResponse);
      }
    } catch (error) {
      console.error("Chat error:", error);
      const fallbackText = buildFriendlyChatError(error);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: fallbackText,
          sources: [],
          images: [],
          timestamp: new Date().toISOString(),
          answerMode: DATABASE_MODE,
        },
      ]);
      toast.error(fallbackText);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(isRecording);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setSessionId(null);
    synthRef.current.cancel();
    setIsSpeaking(false);
  };

  const renderAssistantContent = (message) => {
    if (message.role !== "assistant" || !message.sources?.length) {
      return <p className="whitespace-pre-wrap text-[15px] leading-7">{message.content}</p>;
    }

    const lines = String(message.content || "").split("\n");
    let evidenceLineIndex = 0;

    return (
      <div className="space-y-2">
        {lines.map((line, index) => {
          const trimmed = line.trim();
          if (!trimmed) {
            return <div key={`line-${index}`} className="h-2" />;
          }

          if (/^source:/i.test(trimmed) || /^additional source:/i.test(trimmed)) {
            return null;
          }

          const isHeading = trimmed.endsWith(":") && !trimmed.startsWith("-");
          const sourceIndex = Math.min(evidenceLineIndex, message.sources.length - 1);
          const citation = shouldInlineCite(trimmed) ? message.sources[sourceIndex] : null;
          if (citation && !isHeading) {
            evidenceLineIndex += 1;
          }

          return (
            <p key={`line-${index}`} className={`whitespace-pre-wrap leading-7 ${isHeading ? "font-semibold text-[#0b193c]" : ""}`}>
              {line}
              {citation && !isHeading ? (
                <span className="ml-2 align-super text-[10px] font-semibold text-[#6294ff]" title={citation.document_title}>
                  [{Math.min(sourceIndex + 1, message.sources.length)}]
                </span>
              ) : null}
            </p>
          );
        })}
      </div>
    );
  };

  return (
    <div className="scholar-page flex h-full min-h-0 flex-col overflow-hidden">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 100, damping: 20 }}
        className="flex shrink-0 flex-col gap-4 border-b border-[#e1e7f5] bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(248,249,250,0.72))] px-4 py-5 md:px-6"
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-2xl">
            <p className="section-eyebrow">AI Research Chat</p>
            <h1 className="page-title mt-2">Scholar Pulse Conversation Studio</h1>
            <p className="mt-3 text-sm leading-7 text-[#5c6b8d] md:text-base">
              Database-only mode is active. Every answer is grounded in your indexed academic archive and organized for quick reading.
            </p>
          </div>
          {messages.length > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={clearChat}
              data-testid="clear-chat-btn"
              className="btn-secondary h-11 whitespace-nowrap"
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              New Chat
            </Button>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-3">
          {shortcuts.map((shortcut, index) => (
            <motion.div
              key={shortcut.label}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.06 * index }}
              className="inline-flex items-center gap-2 rounded-full border border-[#d7dff2] bg-white/70 px-4 py-2 text-sm font-semibold text-[#0b193c] shadow-[0_8px_18px_rgba(11,25,60,0.06)] transition hover:scale-[1.02] hover:border-[#6294ff]/35 hover:shadow-[0_12px_22px_rgba(98,148,255,0.12)]"
            >
              <shortcut.icon className="h-4 w-4 text-[#6294ff]" />
              <span>{shortcut.label}</span>
            </motion.div>
          ))}
          <div className="inline-flex items-center gap-2 rounded-full border border-[#6294ff]/18 bg-[#eef3ff] px-4 py-2 text-sm font-semibold text-[#24428a]">
            <BookOpen className="h-4 w-4" />
            <span>Knowledge database only</span>
          </div>
        </div>
      </motion.div>

      <ScrollArea type="always" className="flex-1 min-h-0">
        <div className="mx-auto flex max-w-6xl gap-6 px-4 py-6 md:px-6">
          <div className="min-w-0 flex-1 space-y-5">
            {messages.length === 0 ? (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: "spring", stiffness: 100, damping: 20 }}
                className="scholar-panel-strong relative overflow-hidden p-8 md:p-10"
              >
                <div className="pointer-events-none absolute -right-16 -top-10 h-52 w-52 rounded-full bg-[#6294ff]/14 blur-3xl" />
                <div className="pointer-events-none absolute bottom-0 left-0 h-44 w-44 rounded-full bg-[#b6171e]/8 blur-3xl" />
                <div className="relative z-10">
                  <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-[24px] bg-[#0b193c] text-white shadow-[0_22px_35px_rgba(11,25,60,0.18)]">
                    <Sparkles className="h-10 w-10" />
                  </div>
                  <h2 className="text-3xl font-extrabold text-[#0b193c]">Ask the archive.</h2>
                  <p className="mt-3 max-w-2xl text-base leading-8 text-[#5c6b8d]">
                    Scholar Pulse is tuned for grounded university answers. Ask broad questions for summaries or narrow questions for sharper source-backed detail.
                  </p>
                  <div className="mt-8 flex flex-wrap gap-3">
                    {suggestions.map((suggestion, index) => (
                      <motion.button
                        key={suggestion}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.08 * index }}
                        onClick={() => setInput(suggestion)}
                        className="rounded-full border border-[#d7dff2] bg-white/80 px-4 py-3 text-left text-sm font-semibold text-[#0b193c] shadow-[0_10px_20px_rgba(11,25,60,0.06)] transition hover:scale-[1.02] hover:border-[#6294ff]/35 hover:bg-[#eef3ff]"
                      >
                        {suggestion}
                      </motion.button>
                    ))}
                  </div>
                </div>
              </motion.div>
            ) : (
              <AnimatePresence mode="popLayout">
                {messages.map((message, index) => (
                  <motion.div
                    key={`${message.role}-${index}`}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -20 }}
                    transition={{ type: "spring", stiffness: 100, damping: 20 }}
                    className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div className={message.role === "user" ? "message-user" : "message-assistant"}>
                      {message.role === "assistant" ? (
                        <div className="mb-4 flex items-center justify-between gap-3 border-b border-[#e5eaf7] pb-3">
                          <div>
                            <p className="section-eyebrow">AI Summary</p>
                            <p className="text-sm font-semibold text-[#0b193c]">Grounded knowledge response</p>
                          </div>
                          {message.sources?.length ? (
                            <span className={`rounded-full px-3 py-1 text-[11px] font-semibold ${getDatabaseConfidence(message.sources).className}`}>
                              {getDatabaseConfidence(message.sources).label}
                            </span>
                          ) : null}
                        </div>
                      ) : null}

                      {renderAssistantContent(message)}

                      {message.role === "assistant" && message.images?.length > 0 ? (
                        <div className="mt-5 grid gap-3 lg:grid-cols-2">
                          {message.images.map((image, imageIndex) => (
                            <a
                              key={`${index}-image-${imageIndex}`}
                              href={image.source_url || image.url}
                              target="_blank"
                              rel="noreferrer"
                              className="overflow-hidden rounded-[18px] border border-[#d9e1f4] bg-white shadow-[0_14px_24px_rgba(11,25,60,0.06)] transition hover:scale-[1.01] hover:border-[#6294ff]/35"
                            >
                              <img
                                src={image.url}
                                alt={image.alt || image.source_title || "Chat image"}
                                loading="lazy"
                                className="h-44 w-full object-cover"
                              />
                              <div className="space-y-1 p-4">
                                <p className="text-sm font-semibold text-[#0b193c]">{image.source_title || "Related visual"}</p>
                                <p className="line-clamp-2 text-xs leading-5 text-[#6f7f9f]">
                                  {image.alt || "Open the source image in a new tab"}
                                </p>
                              </div>
                            </a>
                          ))}
                        </div>
                      ) : null}

                      {message.sources?.length ? (
                        <div className="mt-5 border-t border-[#e5eaf7] pt-4">
                          <div className="mb-3 flex items-center gap-2">
                            <FileText className="h-4 w-4 text-[#6294ff]" />
                            <p className="text-sm font-semibold text-[#0b193c]">Source trail</p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {message.sources.map((source, sourceIndex) => (
                              <span key={sourceIndex} className="citation-pill" title={source.chunk_text}>
                                <span className="text-[#6294ff]">[{sourceIndex + 1}]</span>
                                {source.document_title.length > 34 ? `${source.document_title.slice(0, 34)}...` : source.document_title}
                                <span className="text-[#7181a6]">{Math.round(source.relevance_score * 100)}%</span>
                              </span>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {message.role === "assistant" ? (
                        <div className="mt-4 flex items-center gap-3 text-[#7181a6]">
                          <motion.button
                            whileHover={{ scale: 1.08 }}
                            whileTap={{ scale: 0.92 }}
                            onClick={() => speakText(message.content)}
                            className="rounded-full border border-[#d7dff2] bg-white p-2 transition hover:border-[#6294ff]/35 hover:text-[#0b193c]"
                            title={isSpeaking ? "Stop speaking" : "Read aloud"}
                          >
                            {isSpeaking ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.08 }}
                            whileTap={{ scale: 0.92 }}
                            onClick={() => copyResponse(message.content, index)}
                            className="rounded-full border border-[#d7dff2] bg-white p-2 transition hover:border-[#6294ff]/35 hover:text-[#0b193c]"
                            title="Copy response"
                          >
                            {copiedIndex === index ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                          </motion.button>
                          <motion.button
                            whileHover={{ scale: 1.08 }}
                            whileTap={{ scale: 0.92 }}
                            onClick={() => shareResponse(message.content)}
                            className="rounded-full border border-[#d7dff2] bg-white p-2 transition hover:border-[#6294ff]/35 hover:text-[#0b193c]"
                            title="Share response"
                          >
                            <Share2 className="h-4 w-4" />
                          </motion.button>
                        </div>
                      ) : null}
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            )}

            {isLoading ? (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                <div className="message-assistant">
                  <div className="mb-4 flex items-center gap-2 border-b border-[#e5eaf7] pb-3">
                    <Sparkles className="h-4 w-4 text-[#6294ff]" />
                    <p className="text-sm font-semibold text-[#0b193c]">Synthesizing from the archive</p>
                  </div>
                  <div className="space-y-3">
                    <div className="h-2.5 rounded-full shimmer-bar" />
                    <div className="h-2.5 w-[82%] rounded-full shimmer-bar" />
                    <div className="h-2.5 w-[68%] rounded-full shimmer-bar" />
                  </div>
                </div>
              </motion.div>
            ) : null}

            <div ref={messagesEndRef} />
          </div>

          <aside className="sticky top-0 hidden w-[280px] shrink-0 self-start xl:block">
            <div className="scholar-panel p-5">
              <p className="section-eyebrow">Research Hints</p>
              <h3 className="mt-2 text-xl font-extrabold text-[#0b193c]">Ask sharper, get stronger grounding</h3>
              <ul className="mt-4 space-y-3 text-sm leading-6 text-[#5c6b8d]">
                <li>Ask about one theme at a time: admissions, hostels, placements, or facilities.</li>
                <li>Use precise nouns from your documents when you want higher-confidence citations.</li>
                <li>Upload or seed more material when the archive feels thin on a topic.</li>
              </ul>
            </div>
          </aside>
        </div>
      </ScrollArea>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 100, damping: 20 }}
        className="shrink-0 border-t border-[#e1e7f5] bg-[linear-gradient(180deg,rgba(255,255,255,0.78),rgba(248,249,250,0.98))] px-4 py-4 md:px-6"
      >
        <div className="mx-auto max-w-6xl">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {shortcuts.map((shortcut) => (
              <div
                key={shortcut.label}
                className="inline-flex items-center gap-2 rounded-full border border-[#d7dff2] bg-white/80 px-3 py-1.5 text-xs font-semibold text-[#0b193c]"
              >
                <shortcut.icon className="h-3.5 w-3.5 text-[#6294ff]" />
                {shortcut.label}
              </div>
            ))}
          </div>
          <div className="flex items-end gap-3">
            <motion.button
              whileHover={{ scale: 1.04 }}
              whileTap={{ scale: 0.96 }}
              onClick={toggleRecording}
              disabled={isLoading}
              data-testid="voice-record-btn"
              className={`voice-btn ${isRecording ? "recording" : ""}`}
              title={isRecording ? "Stop recording" : "Start voice input"}
            >
              {isRecording ? <MicOff className="h-5 w-5 text-white" /> : <Mic className="h-5 w-5 text-white" />}
            </motion.button>

            <div className="scholar-panel flex-1 p-3 md:p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="section-eyebrow">Knowledge Database</p>
                  <p className="text-sm font-semibold text-[#0b193c]">Grounded archive mode</p>
                </div>
                <span className="rounded-full border border-[#6294ff]/20 bg-[#eef3ff] px-3 py-1 text-xs font-semibold text-[#24428a]">
                  Database only
                </span>
              </div>
              <div className="relative">
                <Textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={isRecording ? "Listening..." : "Ask a grounded question about KRMU, SET, facilities, policies, or uploaded documents..."}
                  disabled={isLoading}
                  data-testid="chat-input"
                  className="input-field min-h-[78px] max-h-40 resize-none pr-14"
                  rows={1}
                />
                <Button
                  onClick={() => sendMessage(isRecording)}
                  disabled={!input.trim() || isLoading}
                  data-testid="send-message-btn"
                  className="absolute bottom-3 right-3 h-10 w-10 rounded-full bg-[#0b193c] p-0 text-white hover:bg-[#15295e] disabled:opacity-50"
                >
                  <Send className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>

          <p className="mt-3 text-center text-xs text-[#7181a6]">
            {isRecording ? "Speak now. Click the mic again to stop." : "Press Enter to send. Shift + Enter creates a new line."}
          </p>
        </div>
      </motion.div>
    </div>
  );
}
