import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import axios from "axios";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { ScrollArea } from "../components/ui/scroll-area";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
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
  Download,
  Eye,
  Pencil,
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
  "What are the latest events in KRMU right now?",
  "What are the key highlights from the B.Tech programme handbook?",
  "Summarize hostel facilities, safety, and student support.",
  "What does the KRMU library offer for study and research?",
  "What are the scholarship and admission support options for new students?",
  "Give me the main placement and recruiter highlights for KRMU.",
];

const PDF_EXPORT_PATTERN =
  /\b(convert|export|save|turn|make|create|download)\b.*\b(this|last|latest|previous|above|response|answer|message|summary|event)\b.*\bpdf\b|\bpdf\b.*\b(this|last|latest|previous|above|response|answer|message|summary|event)\b/i;

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

const normalizeAssistantText = (content) => {
  const lines = String(content || "").split("\n");
  const cleanedLines = [];

  for (const rawLine of lines) {
    let line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      if (cleanedLines[cleanedLines.length - 1] !== "") {
        cleanedLines.push("");
      }
      continue;
    }

    if (/^(key points|highlights|source|additional source|source trail|direct answer|why it matters):\s*$/i.test(trimmed)) {
      continue;
    }

    line = line.replace(/^direct answer:\s*/i, "");
    line = line.replace(/^key points:\s*/i, "");
    line = line.replace(/^highlights:\s*/i, "");
    line = line.replace(/^why it matters:\s*/i, "");
    line = line.replace(/^source:\s*/i, "");
    line = line.replace(/^additional source:\s*/i, "");
    line = line.replace(
      /^what i could not verify from the indexed docs:\s*/i,
      "I couldn't verify from the indexed documents: "
    );

    if (line.trim()) {
      cleanedLines.push(line);
    }
  }

  while (cleanedLines[0] === "") {
    cleanedLines.shift();
  }

  while (cleanedLines[cleanedLines.length - 1] === "") {
    cleanedLines.pop();
  }

  return cleanedLines.join("\n");
};

export default function ChatView() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingMessageIndex, setEditingMessageIndex] = useState(null);
  const [editingArtifact, setEditingArtifact] = useState(null);
  const [editedPdfText, setEditedPdfText] = useState("");
  const [isRegeneratingPdf, setIsRegeneratingPdf] = useState(false);
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

    const outboundMessage = input.trim();
    if (PDF_EXPORT_PATTERN.test(outboundMessage)) {
      await handlePdfExportRequest(outboundMessage);
      return;
    }

    const userMessage = {
      role: "user",
      content: outboundMessage,
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

      const { response: aiResponse, sources, images, artifacts, session_id } = response.data;

      if (!sessionId) {
        setSessionId(session_id);
      }

      const assistantMessage = {
        role: "assistant",
        content: aiResponse,
        sources: sources || [],
        images: images || [],
        artifacts: artifacts || [],
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
          artifacts: [],
          timestamp: new Date().toISOString(),
          answerMode: DATABASE_MODE,
        },
      ]);
      toast.error(fallbackText);
    } finally {
      setIsLoading(false);
    }
  };

  const resolvePdfExportSource = (message) => {
    const lowered = String(message || "").toLowerCase();
    let preferredRole = "assistant";

    if (
      ["my message", "my text", "what i wrote", "user message", "my last", "my previous", "my latest"].some((token) =>
        lowered.includes(token)
      )
    ) {
      preferredRole = "user";
    }

    const searchOrder =
      preferredRole === "assistant"
        ? ["assistant", "user", "system"]
        : [preferredRole, "assistant", "user", "system"];

    for (const role of searchOrder) {
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const item = messages[index];
        if (item?.role !== role) continue;
        const content = String(item?.content || "").trim();
        if (!content) continue;
        return { ...item, content, index };
      }
    }

    return null;
  };

  const handlePdfExportRequest = async (message) => {
    const sourceMessage = resolvePdfExportSource(message);
    const userMessage = {
      role: "user",
      content: message,
      timestamp: new Date().toISOString(),
      answerMode: DATABASE_MODE,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");

    if (!sourceMessage) {
      const fallbackText =
        "I couldn't find a recent message to convert yet. Ask a question first, then say `convert this message to pdf`.";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: fallbackText,
          sources: [],
          images: [],
          artifacts: [],
          timestamp: new Date().toISOString(),
          answerMode: DATABASE_MODE,
        },
      ]);
      toast.error(fallbackText);
      return;
    }

    setIsLoading(true);
    try {
      const titlePrefix = sourceMessage.role === "assistant" ? "Scholar Pulse Reply" : "Scholar Pulse Note";
      const response = await axios.post(`${API}/chat/export-pdf`, {
        content: sourceMessage.content,
        title: `${titlePrefix} PDF`,
        generated_from_role: sourceMessage.role || "assistant",
        images: sourceMessage.images || [],
      });
      const artifact = response.data?.artifact;
      if (!artifact) {
        throw new Error("Missing PDF artifact");
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "I converted the latest message into a PDF with the retrieved images included when available. Use the controls below to view it, edit the text, or download the file.",
          sources: [],
          images: [],
          artifacts: [artifact],
          timestamp: new Date().toISOString(),
          answerMode: DATABASE_MODE,
        },
      ]);
    } catch (error) {
      console.error("PDF export error:", error);
      const fallbackText = error?.response?.data?.detail || "I couldn't create the PDF right now.";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: fallbackText,
          sources: [],
          images: [],
          artifacts: [],
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
    setEditDialogOpen(false);
    setEditingMessageIndex(null);
    setEditingArtifact(null);
    setEditedPdfText("");
    synthRef.current.cancel();
    setIsSpeaking(false);
  };

  const openPdf = (artifact) => {
    if (!artifact?.data_url) {
      toast.error("The PDF is not available yet.");
      return;
    }
    window.open(artifact.data_url, "_blank", "noopener,noreferrer");
  };

  const downloadPdf = (artifact) => {
    if (!artifact?.data_url) {
      toast.error("The PDF is not available yet.");
      return;
    }

    const link = document.createElement("a");
    link.href = artifact.data_url;
    link.download = artifact.filename || "scholar-pulse-export.pdf";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const openEditPdfDialog = (messageIndex, artifact) => {
    setEditingMessageIndex(messageIndex);
    setEditingArtifact(artifact);
    setEditedPdfText(artifact?.text_content || "");
    setEditDialogOpen(true);
  };

  const regeneratePdf = async () => {
    if (editingMessageIndex === null || !editingArtifact) return;
    if (!editedPdfText.trim()) {
      toast.error("Add some text before regenerating the PDF.");
      return;
    }

    setIsRegeneratingPdf(true);
    try {
      const response = await axios.post(`${API}/chat/export-pdf`, {
        content: editedPdfText.trim(),
        title: editingArtifact.title,
        generated_from_role: editingArtifact.generated_from_role || "assistant",
        images: editingArtifact.images || messages[editingMessageIndex]?.images || [],
      });
      const refreshedArtifact = response.data?.artifact;
      if (!refreshedArtifact) {
        throw new Error("Missing regenerated PDF artifact");
      }

      setMessages((prev) =>
        prev.map((message, index) =>
          index === editingMessageIndex
            ? { ...message, artifacts: [refreshedArtifact] }
            : message
        )
      );
      setEditingArtifact(refreshedArtifact);
      setEditDialogOpen(false);
      toast.success("PDF updated successfully.");
    } catch (error) {
      console.error("PDF regeneration error:", error);
      toast.error(error?.response?.data?.detail || "Could not update the PDF.");
    } finally {
      setIsRegeneratingPdf(false);
    }
  };

  const renderAssistantContent = (message) => {
    const normalizedContent = normalizeAssistantText(message.content);
    const lines = normalizedContent.split("\n");
    const textClassName =
      message.role === "user"
        ? "whitespace-pre-wrap text-[15px] leading-7 text-white"
        : "whitespace-pre-wrap text-[15px] leading-7 text-[#223457]";

    return (
      <div className="space-y-2">
        {lines.map((line, index) => {
          const trimmed = line.trim();
          if (!trimmed) {
            return <div key={`line-${index}`} className="h-2" />;
          }

          return (
            <p key={`line-${index}`} className={textClassName}>
              {line}
            </p>
          );
        })}
      </div>
    );
  };

  return (
    <div className="scholar-page flex h-full min-h-0 flex-col overflow-hidden">
      <AnimatePresence initial={false}>
        {messages.length === 0 ? (
          <motion.div
            key="empty-chat-header"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16, height: 0 }}
            transition={{ type: "spring", stiffness: 100, damping: 20 }}
            className="flex shrink-0 flex-col gap-2 border-b border-[#e1e7f5] bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(248,249,250,0.8))] px-4 py-3 md:px-6"
          >
            <div className="max-w-3xl">
              <p className="section-eyebrow">AI Research Chat</p>
              <h1 className="page-title mt-2 font-extrabold text-[#0b193c]">
                Scholar Pulse Conversation Studio
              </h1>
              <p className="mt-2 max-w-2xl text-sm leading-7 text-[#5c6b8d] md:text-base">
                Database-only mode is active. Every answer is grounded in your indexed academic archive and organized for quick reading.
              </p>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <ScrollArea type="always" className="flex-1 min-h-0">
        <div className="mx-auto flex max-w-5xl px-4 py-6 md:px-6">
          <div className="min-w-0 flex-1 space-y-6">
            {messages.length === 0 ? (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: "spring", stiffness: 100, damping: 20 }}
                className="scholar-panel-strong relative overflow-hidden p-6 md:p-8"
              >
                <div className="pointer-events-none absolute -right-20 -top-16 h-48 w-48 rounded-full bg-[#6294ff]/12 blur-3xl" />
                <div className="pointer-events-none absolute bottom-0 left-0 h-36 w-36 rounded-full bg-[#b6171e]/7 blur-3xl" />
                <div className="relative z-10 grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.9fr)] lg:items-start">
                  <div>
                    <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-[20px] bg-[#0b193c] text-white shadow-[0_18px_30px_rgba(11,25,60,0.16)]">
                      <Sparkles className="h-8 w-8" />
                    </div>
                    <h2 className="text-[30px] font-extrabold leading-tight text-[#0b193c]">Ask the archive.</h2>
                    <p className="mt-3 max-w-2xl text-[15px] leading-7 text-[#5c6b8d]">
                      Start with one focused topic and Scholar Pulse will organize the answer around your indexed KRMU material.
                    </p>
                    <div className="mt-5 flex flex-wrap gap-2.5">
                      {shortcuts.map((shortcut, index) => (
                        <motion.div
                          key={shortcut.label}
                          initial={{ opacity: 0, y: 20 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.05 * index }}
                          className="inline-flex items-center gap-2 rounded-full border border-[#d7dff2] bg-white/75 px-3.5 py-2 text-xs font-semibold text-[#0b193c]"
                        >
                          <shortcut.icon className="h-3.5 w-3.5 text-[#6294ff]" />
                          <span>{shortcut.label}</span>
                        </motion.div>
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-3">
                    {suggestions.map((suggestion, index) => (
                      <motion.button
                        key={suggestion}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.08 * index }}
                        onClick={() => setInput(suggestion)}
                        className="rounded-[18px] border border-[#d7dff2] bg-white/82 px-4 py-4 text-left shadow-[0_10px_20px_rgba(11,25,60,0.05)] transition hover:scale-[1.01] hover:border-[#6294ff]/35 hover:bg-[#eef3ff]"
                      >
                        <p className="section-eyebrow">Suggested prompt</p>
                        <p className="mt-2 text-sm font-semibold leading-6 text-[#0b193c]">{suggestion}</p>
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

                      {message.role === "assistant" && message.artifacts?.length > 0 ? (
                        <div className="mt-5 space-y-3">
                          {message.artifacts.map((artifact, artifactIndex) => (
                            <div
                              key={`${index}-artifact-${artifactIndex}`}
                              className="rounded-[18px] border border-[#d7dff2] bg-white/86 p-4 shadow-[0_14px_24px_rgba(11,25,60,0.05)]"
                            >
                              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                                <div>
                                  <p className="section-eyebrow">PDF Export</p>
                                  <p className="mt-1 text-sm font-semibold text-[#0b193c]">{artifact.title}</p>
                                  <p className="mt-1 text-xs text-[#7181a6]">{artifact.filename}</p>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => openPdf(artifact)}
                                    className="btn-secondary h-10"
                                  >
                                    <Eye className="mr-2 h-4 w-4" />
                                    View
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => openEditPdfDialog(index, artifact)}
                                    className="btn-secondary h-10"
                                  >
                                    <Pencil className="mr-2 h-4 w-4" />
                                    Edit
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    onClick={() => downloadPdf(artifact)}
                                    className="btn-primary h-10"
                                  >
                                    <Download className="mr-2 h-4 w-4" />
                                    Download
                                  </Button>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : null}

                      {message.sources?.length ? (
                        <div className="mt-5 border-t border-[#e5eaf7] pt-4">
                          <div className="mb-3 flex flex-wrap items-center gap-2.5">
                            <span className="inline-flex items-center gap-2 rounded-full border border-[#d7dff2] bg-white px-3 py-1.5 text-xs font-semibold text-[#3c4c71]">
                              <FileText className="h-3.5 w-3.5 text-[#6294ff]" />
                              Sources
                            </span>
                            <span className={`rounded-full px-3 py-1.5 text-[11px] font-semibold ${getDatabaseConfidence(message.sources).className}`}>
                              {getDatabaseConfidence(message.sources).label}
                            </span>
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
        </div>
      </ScrollArea>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 100, damping: 20 }}
        className="shrink-0 border-t border-[#e1e7f5] bg-[linear-gradient(180deg,rgba(255,255,255,0.82),rgba(248,249,250,0.98))] px-4 py-4 md:px-6"
      >
        <div className="mx-auto max-w-5xl">
          {messages.length > 0 ? (
            <div className="mb-3 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={clearChat}
                data-testid="clear-chat-btn"
                className="btn-secondary h-9 rounded-full px-4 text-xs"
              >
                <RotateCcw className="mr-2 h-3.5 w-3.5" />
                New Chat
              </Button>
            </div>
          ) : null}
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

      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-2xl border-[#d7dff2] bg-white/96">
          <DialogHeader>
            <DialogTitle className="font-heading text-[#0b193c]">Edit PDF Content</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-[#5c6b8d]">
              Update the text below and regenerate the PDF when you're ready.
            </p>
            <Textarea
              value={editedPdfText}
              onChange={(event) => setEditedPdfText(event.target.value)}
              className="input-field min-h-[280px]"
              placeholder="Edit the PDF content here..."
            />
            <div className="flex justify-end gap-3">
              <Button type="button" variant="ghost" onClick={() => setEditDialogOpen(false)} className="btn-secondary">
                Cancel
              </Button>
              <Button type="button" onClick={regeneratePdf} className="btn-primary" disabled={isRegeneratingPdf}>
                {isRegeneratingPdf ? "Updating..." : "Update PDF"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
