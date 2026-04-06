import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import axios from "axios";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Textarea } from "../components/ui/textarea";
import { ScrollArea } from "../components/ui/scroll-area";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../components/ui/alert-dialog";
import {
  Database,
  Cpu,
  RefreshCw,
  Trash2,
  Sparkles,
  CheckCircle,
  XCircle,
  Loader2,
  BookOpen,
  GraduationCap,
  Search,
} from "lucide-react";

import { API } from "../lib/api";

export default function KnowledgeBaseSettings() {
  const [status, setStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSeeding, setIsSeeding] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [evaluationQuery, setEvaluationQuery] = useState("");
  const [evaluationResult, setEvaluationResult] = useState(null);
  const [isEvaluating, setIsEvaluating] = useState(false);

  const fetchStatus = async () => {
    try {
      const response = await axios.get(`${API}/admin/seed-status`);
      setStatus(response.data);
    } catch (error) {
      console.error("Error fetching seed status:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const seedKnowledgeBase = async () => {
    setIsSeeding(true);
    try {
      await axios.post(`${API}/admin/seed-knowledge-base`);
      toast.success("Knowledge base seeding started! This may take a few minutes.");
      // Poll for updates
      const interval = setInterval(async () => {
        await fetchStatus();
      }, 5000);
      setTimeout(() => clearInterval(interval), 60000); // Stop polling after 1 min
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to seed knowledge base");
    } finally {
      setIsSeeding(false);
    }
  };

  const clearSeeds = async () => {
    setIsClearing(true);
    try {
      await axios.delete(`${API}/admin/clear-seeds`);
      toast.success("Seeded documents cleared");
      fetchStatus();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to clear seeds");
    } finally {
      setIsClearing(false);
    }
  };

  const refreshModels = async () => {
    setIsRefreshing(true);
    try {
      const response = await axios.post(`${API}/admin/refresh-ollama`);
      if (response.data.remote_llm_available) {
        toast.success(response.data.message || "Remote model connection is active.");
      } else if (response.data.ollama_available) {
        toast.success(response.data.message || "Ollama fallback connected successfully.");
      } else {
        toast.warning(response.data.message || "No model provider is currently available.");
      }
      fetchStatus();
    } catch (error) {
      toast.error("Failed to refresh model connection");
    } finally {
      setIsRefreshing(false);
    }
  };

  const runRetrievalCheck = async () => {
    if (!evaluationQuery.trim()) {
      toast.error("Enter a question to inspect retrieval");
      return;
    }

    setIsEvaluating(true);
    try {
      const response = await axios.post(`${API}/admin/retrieval-evaluate`, {
        query: evaluationQuery.trim(),
        top_k: 5,
      });
      setEvaluationResult(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to inspect retrieval");
    } finally {
      setIsEvaluating(false);
    }
  };

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-[#FFBA00]" />
      </div>
    );
  }

  const ollamaAvailable = status?.rag_stats?.ollama_available;
  const remoteLlmAvailable = status?.rag_stats?.remote_llm_available;
  const chatProvider = status?.rag_stats?.chat_provider || "unknown";
  const isAiAvailable = Boolean(remoteLlmAvailable || ollamaAvailable);
  const categories = status?.categories || {};

  return (
    <div className="space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <div className="w-10 h-10 bg-[#FFBA00]/10 rounded-xl flex items-center justify-center border border-[#FFBA00]/30">
          <Database className="w-5 h-5 text-[#FFBA00]" />
        </div>
        <div>
          <h2 className="text-xl font-heading font-bold text-white">
            Knowledge Base Settings
          </h2>
          <p className="text-sm text-[#6b7280]">
            Manage RAG documents and model-provider connectivity
          </p>
        </div>
      </motion.div>

      {/* Status Cards */}
      <div className="grid md:grid-cols-2 gap-4">
        {/* Model Provider Status */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="card-surface p-5"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Cpu className="w-5 h-5 text-[#FFBA00]" />
              <h3 className="font-heading font-semibold text-white">Model Provider</h3>
            </div>
            <Badge
              variant="outline"
              className={
                isAiAvailable
                  ? "bg-green-500/20 text-green-400 border-green-500/30"
                  : "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
              }
            >
              {isAiAvailable ? (
                <><CheckCircle className="w-3 h-3 mr-1" /> Connected</>
              ) : (
                <><XCircle className="w-3 h-3 mr-1" /> Unavailable</>
              )}
            </Badge>
          </div>
          <div className="space-y-2 text-sm text-[#9ca3af] mb-4">
            <p>
              <span className="text-[#6b7280]">Active Provider:</span>{" "}
              {chatProvider === "vllm"
                ? "Remote LLM (Groq-compatible)"
                : chatProvider === "ollama"
                  ? "Ollama"
                  : "Unavailable"}
            </p>
            <p>
              <span className="text-[#6b7280]">Chat Model:</span>{" "}
              {status?.rag_stats?.chat_model || "N/A"}
            </p>
            <p>
              <span className="text-[#6b7280]">Embedding Provider:</span>{" "}
              {status?.rag_stats?.embedding_provider || "N/A"}
            </p>
            <p>
              <span className="text-[#6b7280]">Embedding Model:</span>{" "}
              {status?.rag_stats?.embedding_model || "N/A"}
            </p>
          </div>
          <Button
            onClick={refreshModels}
            disabled={isRefreshing}
            variant="outline"
            size="sm"
            className="w-full bg-[#1e2330] border-[#2a3142] text-white hover:bg-[#2a3142]"
          >
            {isRefreshing ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4 mr-2" />
            )}
            Refresh Model Status
          </Button>
        </motion.div>

        {/* Knowledge Base Status */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="card-surface p-5"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-[#FFBA00]" />
              <h3 className="font-heading font-semibold text-white">Knowledge Base</h3>
            </div>
            <Badge variant="outline" className="bg-[#FFBA00]/20 text-[#FFBA00] border-[#FFBA00]/30">
              {status?.rag_stats?.total_chunks || 0} chunks
            </Badge>
          </div>
          <div className="space-y-2 text-sm text-[#9ca3af] mb-4">
            <p>
              <span className="text-[#6b7280]">Seeded Documents:</span>{" "}
              {status?.seeded_documents || 0}
            </p>
            <p>
              <span className="text-[#6b7280]">Total Documents:</span>{" "}
              {status?.total_documents || 0}
            </p>
          </div>
          {Object.keys(categories).length > 0 && (
            <div className="flex flex-wrap gap-1 mb-4">
              {Object.entries(categories).map(([cat, count]) => (
                <Badge key={cat} variant="outline" className="text-xs bg-[#1e2330] border-[#2a3142]">
                  {cat}: {count}
                </Badge>
              ))}
            </div>
          )}
        </motion.div>
      </div>

      {/* Actions */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="card-surface p-5"
      >
        <h3 className="font-heading font-semibold text-white mb-4 flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-[#FFBA00]" />
          Seed Knowledge Base
        </h3>
        <p className="text-sm text-[#6b7280] mb-4">
          Automatically fetch and index official SET/KRMU documents including:
        </p>
        <ul className="text-sm text-[#9ca3af] mb-4 space-y-1 ml-4">
          <li className="flex items-center gap-2">
            <GraduationCap className="w-4 h-4 text-[#FFBA00]" />
            University & SET overview pages
          </li>
          <li className="flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-[#FFBA00]" />
            Academic programs & curriculum
          </li>
          <li className="flex items-center gap-2">
            <Database className="w-4 h-4 text-[#FFBA00]" />
            Faculty directory & policies
          </li>
        </ul>
        <div className="flex gap-3">
          <Button
            onClick={seedKnowledgeBase}
            disabled={isSeeding || (status?.seeded_documents || 0) > 0}
            className="btn-primary flex-1"
            data-testid="seed-knowledge-base-btn"
          >
            {isSeeding ? (
              <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Seeding...</>
            ) : (status?.seeded_documents || 0) > 0 ? (
              <><CheckCircle className="w-4 h-4 mr-2" /> Already Seeded</>
            ) : (
              <><Sparkles className="w-4 h-4 mr-2" /> Seed Knowledge Base</>
            )}
          </Button>
          {(status?.seeded_documents || 0) > 0 && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="outline"
                  disabled={isClearing}
                  className="bg-[#1e2330] border-red-500/30 text-red-400 hover:bg-red-500/10"
                >
                  {isClearing ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent className="bg-[#1a1e26] border-[#2a3142]">
                <AlertDialogHeader>
                  <AlertDialogTitle className="text-white">Clear Seeded Documents</AlertDialogTitle>
                  <AlertDialogDescription className="text-[#9ca3af]">
                    This will remove all automatically seeded documents from the knowledge base.
                    User-uploaded documents will not be affected.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel className="bg-[#2a3142] text-white border-[#3f4556] hover:bg-[#3f4556]">
                    Cancel
                  </AlertDialogCancel>
                  <AlertDialogAction
                    onClick={clearSeeds}
                    className="bg-red-500 text-white hover:bg-red-600"
                  >
                    Clear Seeds
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35 }}
        className="card-surface p-5"
      >
        <h3 className="font-heading font-semibold text-white mb-3 flex items-center gap-2">
          <Search className="w-5 h-5 text-[#FFBA00]" />
          Retrieval Check
        </h3>
        <p className="text-sm text-[#6b7280] mb-4">
          Test a database-mode question and inspect which chunks the retriever is selecting before answer generation.
        </p>
        <div className="space-y-3">
          <Textarea
            value={evaluationQuery}
            onChange={(e) => setEvaluationQuery(e.target.value)}
            placeholder="Example: Tell me about K.R. Mangalam University"
            className="input-field min-h-[96px]"
          />
          <Button
            onClick={runRetrievalCheck}
            disabled={isEvaluating}
            className="btn-primary"
          >
            {isEvaluating ? (
              <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Checking...</>
            ) : (
              <><Search className="w-4 h-4 mr-2" />Inspect Retrieval</>
            )}
          </Button>
        </div>

        {evaluationResult ? (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline" className="bg-[#1e2330] border-[#2a3142] text-[#9ca3af]">
                backend: {evaluationResult.vector_backend}
              </Badge>
              <Badge variant="outline" className="bg-[#1e2330] border-[#2a3142] text-[#9ca3af]">
                embeddings: {evaluationResult.embedding_provider}
              </Badge>
              <Badge variant="outline" className="bg-[#1e2330] border-[#2a3142] text-[#9ca3af]">
                model: {evaluationResult.embedding_model}
              </Badge>
            </div>
            <ScrollArea className="h-[260px] pr-4">
              <div className="space-y-3">
                {evaluationResult.results?.length ? evaluationResult.results.map((item) => (
                  <div key={`${item.metadata?.document_id || "doc"}-${item.chunk_index}`} className="rounded-xl border border-[#2a3142] bg-[#12151a] p-4">
                    <div className="flex flex-wrap items-center gap-2 mb-2 text-xs">
                      <Badge variant="outline" className="bg-[#FFBA00]/10 border-[#FFBA00]/30 text-[#FFBA00]">
                        score {Number(item.relevance_score || 0).toFixed(3)}
                      </Badge>
                      <span className="text-[#9ca3af]">{item.metadata?.document_title || "Unknown source"}</span>
                      <span className="text-[#6b7280]">chunk {item.chunk_index}</span>
                    </div>
                    <p className="text-sm text-[#d1d5db] leading-6 whitespace-pre-wrap">{item.chunk_text}</p>
                  </div>
                )) : (
                  <p className="text-sm text-[#6b7280]">No chunks were retrieved for that question.</p>
                )}
              </div>
            </ScrollArea>
          </div>
        ) : null}
      </motion.div>

      {/* Model Setup Instructions */}
      {!isAiAvailable && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="card-surface p-5 border-l-4 border-yellow-500"
        >
          <h3 className="font-heading font-semibold text-white mb-2">
            Enable Intelligent Responses
          </h3>
          <p className="text-sm text-[#6b7280] mb-3">
            No active model provider is available right now. Enable either the remote LLM or Ollama:
          </p>
          <div className="bg-[#12151a] rounded-lg p-4 font-mono text-sm text-[#9ca3af]">
            <p className="text-[#FFBA00] mb-2"># Remote provider</p>
            <p className="mb-2">Set LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL in the backend environment</p>
            <p className="text-[#FFBA00] mb-2"># Install Ollama</p>
            <p className="mb-2">curl -fsSL https://ollama.com/install.sh | sh</p>
            <p className="text-[#FFBA00] mb-2"># Pull a model (choose one)</p>
            <p className="mb-1">ollama pull llama3</p>
            <p className="mb-2">ollama pull mistral</p>
            <p className="text-[#FFBA00] mb-2"># For embeddings</p>
            <p className="mb-2">ollama pull nomic-embed-text</p>
            <p className="text-[#FFBA00] mb-2"># Start Ollama server</p>
            <p>ollama serve</p>
          </div>
          <p className="text-xs text-[#6b7280] mt-3">
            After setup, click "Refresh Model Status" to re-check provider availability.
          </p>
        </motion.div>
      )}
    </div>
  );
}
