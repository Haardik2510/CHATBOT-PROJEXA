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
  Globe,
} from "lucide-react";

import { API } from "../lib/api";

const getDatabaseConfidence = (sources = []) => {
  const bestScore = Math.max(...sources.map((source) => Number(source?.relevance_score || 0)), 0);
  if (bestScore >= 0.82) {
    return { label: "High confidence", className: "bg-green-500/15 text-green-400 border border-green-500/30" };
  }
  if (bestScore >= 0.62) {
    return { label: "Medium confidence", className: "bg-yellow-500/15 text-yellow-400 border border-yellow-500/30" };
  }
  return { label: "Low confidence", className: "bg-red-500/15 text-red-400 border border-red-500/30" };
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
  const [answerMode, setAnswerMode] = useState("database");
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const messagesEndRef = useRef(null);
  const recognitionRef = useRef(null);
  const synthRef = useRef(window.speechSynthesis);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Initialize speech recognition
  useEffect(() => {
    if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
      const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;
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
    } else {
      setInput("");
      recognitionRef.current.start();
      setIsRecording(true);
    }
  };

  const speakText = (text) => {
    if (isSpeaking) {
      synthRef.current.cancel();
      setIsSpeaking(false);
      return;
    }

    // Clean text for speech
    const cleanText = text.replace(/\*\*/g, '').replace(/\*/g, '').replace(/_/g, '');
    
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
      return "I’m having trouble reaching the knowledge services right now, but your message was received. Please try again in a moment.";
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
          title: "SET Academic Assistant Response",
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
      answerMode,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await axios.post(`${API}/chat`, {
        message: userMessage.content,
        session_id: sessionId,
        voice_input: voiceInput,
        answer_mode: answerMode,
      });

      const { response: aiResponse, sources, session_id, answer_mode } = response.data;

      if (!sessionId) {
        setSessionId(session_id);
      }

      const assistantMessage = {
        role: "assistant",
        content: aiResponse,
        sources: sources,
        timestamp: new Date().toISOString(),
        answerMode: answer_mode || answerMode,
        isWebFallback:
          (answer_mode || answerMode) === "internet" ||
          sources?.some(s => s.document_id?.startsWith("web_")),
      };

      setMessages((prev) => [...prev, assistantMessage]);

      // Auto-speak if voice input was used
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
          timestamp: new Date().toISOString(),
          answerMode,
          isWebFallback: false,
        },
      ]);
      toast.error(fallbackText);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(isRecording);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setSessionId(null);
    synthRef.current.cancel();
    setIsSpeaking(false);
  };

  const suggestions = [
    "What are the admission requirements?",
    "Tell me about B.Tech programs",
    "What facilities does SET offer?",
  ];

  const answerModeOptions = [
    {
      value: "database",
      label: "Database",
      description: "Use indexed campus documents",
      icon: FileText,
    },
    {
      value: "internet",
      label: "Internet",
      description: "Use DuckDuckGo web results",
      icon: Globe,
    },
  ];

  const renderAssistantContent = (message) => {
    if (message.role !== "assistant" || message.answerMode !== "database" || !message.sources?.length) {
      return <p className="whitespace-pre-wrap">{message.content}</p>;
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
            <p key={`line-${index}`} className="whitespace-pre-wrap leading-7">
              {line}
              {citation && !isHeading ? (
                <span
                  className="ml-2 align-super text-[10px] font-semibold text-[#FFBA00]/85"
                  title={citation.document_title}
                >
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
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#12151a]">
      {/* Header */}
      <motion.div 
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="shrink-0 border-b border-[#1e2330] bg-[#12151a] p-4 md:p-6"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#FFBA00]/10 rounded-xl flex items-center justify-center border border-[#FFBA00]/30">
              <Sparkles className="w-5 h-5 text-[#FFBA00]" />
            </div>
            <div>
              <h1 className="text-xl font-heading font-bold text-white">
                Academic Assistant
              </h1>
              <p className="text-sm text-[#6b7280]">
                Ask questions about SET curriculum, policies, and resources
              </p>
            </div>
          </div>
          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={clearChat}
              data-testid="clear-chat-btn"
              className="text-[#6b7280] hover:text-white hover:bg-[#1e2330]"
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              New Chat
            </Button>
          )}
        </div>
      </motion.div>

      {/* Messages area */}
      <ScrollArea type="always" className="flex-1 min-h-0">
        <div className="max-w-3xl mx-auto space-y-4 p-4 pr-5 md:p-6 md:pr-6">
          {messages.length === 0 ? (
            <motion.div 
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.5 }}
              className="text-center py-12"
            >
              <motion.div 
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: "spring", stiffness: 200, delay: 0.2 }}
                className="w-20 h-20 bg-[#FFBA00]/10 rounded-2xl flex items-center justify-center mx-auto mb-6 border border-[#FFBA00]/30 glow-effect"
              >
                <Sparkles className="w-10 h-10 text-[#FFBA00]" />
              </motion.div>
              <motion.h2 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3 }}
                className="text-2xl font-heading font-bold text-white mb-3"
              >
                Welcome to SET Academic Assistant
              </motion.h2>
              <motion.p 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4 }}
                className="text-[#6b7280] max-w-md mx-auto mb-8"
              >
                I can help you with information about the School of Engineering
                & Technology curriculum, policies, faculty, and more.
              </motion.p>
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 }}
                className="space-y-4"
              >
                <div className="flex flex-wrap items-center justify-center gap-2">
                  {answerModeOptions.map((option, i) => (
                    <motion.button
                      key={option.value}
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: 0.55 + i * 0.08 }}
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => setAnswerMode(option.value)}
                      className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm transition-all duration-200 ${
                        answerMode === option.value
                          ? "border-[#FFBA00]/40 bg-[#FFBA00]/10 text-[#FFBA00]"
                          : "border-[#2a3142] bg-[#1a1e26] text-[#9ca3af] hover:text-[#FFBA00] hover:border-[#FFBA00]/30"
                      }`}
                    >
                      <option.icon className="h-4 w-4" />
                      <span>{option.label}</span>
                    </motion.button>
                  ))}
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {suggestions.map((suggestion, i) => (
                    <motion.button
                      key={suggestion}
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: 0.7 + i * 0.1 }}
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => setInput(suggestion)}
                      className="px-4 py-2.5 text-sm bg-[#1a1e26] border border-[#2a3142] rounded-xl text-[#9ca3af] hover:text-[#FFBA00] hover:border-[#FFBA00]/30 transition-all duration-200"
                    >
                      {suggestion}
                    </motion.button>
                  ))}
                </div>
              </motion.div>
            </motion.div>
          ) : (
            <AnimatePresence mode="popLayout">
              {messages.map((message, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 20, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -20, scale: 0.95 }}
                  transition={{ duration: 0.3 }}
                  className={`flex ${
                    message.role === "user" ? "justify-end" : "justify-start"
                  }`}
                >
                  <div
                    className={
                      message.role === "user"
                        ? "message-user"
                        : "message-assistant"
                    }
                  >
                    {renderAssistantContent(message)}

                    {/* Sources/Citations */}
                    {message.sources && message.sources.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-[#2a3142]">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                          <p className="text-xs text-[#6b7280] flex items-center gap-1">
                            {message.answerMode === "internet" || message.isWebFallback ? (
                              <>
                                <Globe className="w-3 h-3" />
                                Internet Sources
                              </>
                            ) : (
                              <>
                                <FileText className="w-3 h-3" />
                                Database Sources
                              </>
                            )}
                          </p>
                          {message.answerMode === "database" && !message.isWebFallback ? (
                            <span className={`rounded-full px-2 py-1 text-[11px] ${getDatabaseConfidence(message.sources).className}`}>
                              {getDatabaseConfidence(message.sources).label}
                            </span>
                          ) : null}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {message.sources.map((source, i) => (
                            <span
                              key={i}
                              className="citation-pill"
                              title={source.chunk_text}
                            >
                              {message.answerMode === "database" && !message.isWebFallback ? (
                                <span className="mr-1 text-[#FFBA00]">[{i + 1}]</span>
                              ) : null}
                              {source.document_title.length > 30 
                                ? source.document_title.slice(0, 30) + '...'
                                : source.document_title}
                              <span className="text-[#FFBA00]/60 ml-1">
                                {Math.round(source.relevance_score * 100)}%
                              </span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Speak button for assistant messages */}
                    {message.role === "assistant" && (
                      <div className="mt-2 flex items-center gap-3 text-[#6b7280]">
                        <motion.button
                          whileHover={{ scale: 1.1 }}
                          whileTap={{ scale: 0.9 }}
                          onClick={() => speakText(message.content)}
                          className="hover:text-[#FFBA00] transition-colors"
                          title={isSpeaking ? "Stop speaking" : "Read aloud"}
                        >
                          {isSpeaking ? (
                            <VolumeX className="w-4 h-4" />
                          ) : (
                            <Volume2 className="w-4 h-4" />
                          )}
                        </motion.button>
                        <motion.button
                          whileHover={{ scale: 1.1 }}
                          whileTap={{ scale: 0.9 }}
                          onClick={() => copyResponse(message.content, index)}
                          className="hover:text-[#FFBA00] transition-colors"
                          title="Copy response"
                        >
                          {copiedIndex === index ? (
                            <Check className="w-4 h-4" />
                          ) : (
                            <Copy className="w-4 h-4" />
                          )}
                        </motion.button>
                        <motion.button
                          whileHover={{ scale: 1.1 }}
                          whileTap={{ scale: 0.9 }}
                          onClick={() => shareResponse(message.content)}
                          className="hover:text-[#FFBA00] transition-colors"
                          title="Share response"
                        >
                          <Share2 className="w-4 h-4" />
                        </motion.button>
                      </div>
                    )}
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          )}

          {/* Loading indicator */}
          {isLoading && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex justify-start"
            >
              <div className="message-assistant">
                <div className="flex items-center gap-2">
                  <motion.div 
                    animate={{ scale: [1, 1.2, 1] }}
                    transition={{ repeat: Infinity, duration: 0.6, delay: 0 }}
                    className="w-2 h-2 bg-[#FFBA00] rounded-full"
                  />
                  <motion.div 
                    animate={{ scale: [1, 1.2, 1] }}
                    transition={{ repeat: Infinity, duration: 0.6, delay: 0.15 }}
                    className="w-2 h-2 bg-[#FFBA00] rounded-full"
                  />
                  <motion.div 
                    animate={{ scale: [1, 1.2, 1] }}
                    transition={{ repeat: Infinity, duration: 0.6, delay: 0.3 }}
                    className="w-2 h-2 bg-[#FFBA00] rounded-full"
                  />
                </div>
              </div>
            </motion.div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>

      {/* Input area */}
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="shrink-0 border-t border-[#1e2330] bg-[#0f1115] p-4 md:p-6"
      >
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-3">
            {/* Voice button */}
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={toggleRecording}
              disabled={isLoading}
              data-testid="voice-record-btn"
              className={`voice-btn ${isRecording ? "recording" : ""}`}
              title={isRecording ? "Stop recording" : "Start voice input"}
            >
              {isRecording ? (
                <MicOff className="w-5 h-5 text-white" />
              ) : (
                <Mic className="w-5 h-5 text-[#12151a]" />
              )}
            </motion.button>

            {/* Text input */}
            <div className="flex-1 relative">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {answerModeOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setAnswerMode(option.value)}
                    className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                      answerMode === option.value
                        ? "border-[#FFBA00]/40 bg-[#FFBA00]/10 text-[#FFBA00]"
                        : "border-[#2a3142] bg-[#12151a] text-[#9ca3af] hover:border-[#FFBA00]/30 hover:text-[#FFBA00]"
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
                <span className="text-xs text-[#6b7280]">
                  {answerMode === "database"
                    ? "Grounded in indexed SET/KRMU documents"
                    : "Answered from DuckDuckGo web search"}
                </span>
              </div>
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  isRecording
                    ? "Listening..."
                    : "Ask a question about SET..."
                }
                disabled={isLoading}
                data-testid="chat-input"
                className="input-field min-h-[52px] max-h-32 resize-none pr-12"
                rows={1}
              />
              <Button
                onClick={() => sendMessage(isRecording)}
                disabled={!input.trim() || isLoading}
                data-testid="send-message-btn"
                className="absolute right-2 bottom-2 w-8 h-8 p-0 rounded-lg bg-[#FFBA00] hover:bg-[#e5a800] disabled:opacity-50"
              >
                <Send className="w-4 h-4 text-[#12151a]" />
              </Button>
            </div>
          </div>

          <p className="text-xs text-[#6b7280] mt-3 text-center">
            {isRecording
              ? "Speak now... Click mic to stop"
              : "Press Enter to send | Shift+Enter for new line"}
          </p>
        </div>
      </motion.div>
    </div>
  );
}
