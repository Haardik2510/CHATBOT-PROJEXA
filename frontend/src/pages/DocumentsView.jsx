import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import axios from "axios";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { ScrollArea } from "../components/ui/scroll-area";
import { Checkbox } from "../components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
import { Badge } from "../components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import {
  Upload,
  Link as LinkIcon,
  FileText,
  File,
  FileSpreadsheet,
  Presentation,
  Globe,
  Trash2,
  RefreshCw,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  Settings,
  Eye,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import KnowledgeBaseSettings from "../components/KnowledgeBaseSettings";

import { API } from "../lib/api";

const fileTypeIcons = {
  pdf: FileText,
  docx: File,
  txt: FileText,
  csv: FileSpreadsheet,
  pptx: Presentation,
  url: Globe,
};

const statusColors = {
  pending: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  processing: "bg-[#FFBA00]/20 text-[#FFBA00] border-[#FFBA00]/30",
  indexed: "bg-green-500/20 text-green-400 border-green-500/30",
  failed: "bg-red-500/20 text-red-400 border-red-500/30",
};

const statusIcons = {
  pending: Clock,
  processing: Loader2,
  indexed: CheckCircle,
  failed: XCircle,
};

export default function DocumentsView() {
  const { isAdmin } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState(null);

  const [fileUpload, setFileUpload] = useState({
    file: null,
    title: "",
    description: "",
  });

  const [urlUpload, setUrlUpload] = useState({
    url: "",
    title: "",
    description: "",
  });

  const fetchDocuments = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setIsLoading(true);
    } else {
      setIsRefreshing(true);
    }
    try {
      const response = await axios.get(`${API}/documents`);
      setDocuments(response.data);
    } catch (error) {
      console.error("Error fetching documents:", error);
      if (!silent) {
        setDocuments([]);
        toast.error(error.response?.data?.detail || "Failed to load documents");
      }
    } finally {
      if (!silent) {
        setIsLoading(false);
      } else {
        setIsRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  useEffect(() => {
    const hasProcessing = documents.some(
      (doc) => doc.status === "pending" || doc.status === "processing"
    );

    if (hasProcessing) {
      const interval = setInterval(() => fetchDocuments({ silent: true }), 5000);
      return () => clearInterval(interval);
    }
  }, [documents, fetchDocuments]);

  useEffect(() => {
    setSelectedDocumentIds((prev) =>
      prev.filter((id) => documents.some((doc) => doc.id === id))
    );
  }, [documents]);

  const handleFileSelect = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      setFileUpload((prev) => ({
        ...prev,
        file,
        title: prev.title || file.name.replace(/\.[^/.]+$/, ""),
      }));
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      setFileUpload((prev) => ({
        ...prev,
        file,
        title: prev.title || file.name.replace(/\.[^/.]+$/, ""),
      }));
    }
  };

  const uploadFile = async () => {
    if (!fileUpload.file || !fileUpload.title) {
      toast.error("Please select a file and provide a title");
      return;
    }

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", fileUpload.file);
    formData.append("title", fileUpload.title);
    if (fileUpload.description) {
      formData.append("description", fileUpload.description);
    }

    try {
      await axios.post(`${API}/documents/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success("Document uploaded and queued for indexing");
      setFileUpload({ file: null, title: "", description: "" });
      setUploadDialogOpen(false);
      fetchDocuments();
    } catch (error) {
      console.error("Upload error:", error);
      toast.error(error.response?.data?.detail || "Upload failed");
    } finally {
      setIsUploading(false);
    }
  };

  const addUrl = async () => {
    if (!urlUpload.url) {
      toast.error("Please enter a URL");
      return;
    }

    setIsUploading(true);
    try {
      await axios.post(`${API}/documents/url`, urlUpload);
      toast.success("URL queued for scraping");
      setUrlUpload({ url: "", title: "", description: "" });
      setUploadDialogOpen(false);
      fetchDocuments();
    } catch (error) {
      console.error("URL add error:", error);
      toast.error(error.response?.data?.detail || "Failed to add URL");
    } finally {
      setIsUploading(false);
    }
  };

  const deleteDocument = async (id) => {
    if (!window.confirm("Are you sure you want to delete this document?")) {
      return;
    }

    try {
      await axios.delete(`${API}/documents/${id}`);
      toast.success("Document deleted");
      fetchDocuments();
    } catch (error) {
      console.error("Delete error:", error);
      toast.error(error.response?.data?.detail || "Failed to delete document");
    }
  };

  const toggleDocumentSelection = (documentId, checked) => {
    setSelectedDocumentIds((prev) => {
      if (checked) {
        return prev.includes(documentId) ? prev : [...prev, documentId];
      }
      return prev.filter((id) => id !== documentId);
    });
  };

  const toggleSelectAll = (checked) => {
    if (!checked) {
      setSelectedDocumentIds([]);
      return;
    }
    setSelectedDocumentIds(documents.map((doc) => doc.id));
  };

  const bulkDeleteDocuments = async () => {
    if (!selectedDocumentIds.length) {
      toast.error("Select at least one document to delete");
      return;
    }

    const selectedCount = selectedDocumentIds.length;
    if (!window.confirm(`Delete ${selectedCount} selected document${selectedCount > 1 ? "s" : ""}?`)) {
      return;
    }

    setIsBulkDeleting(true);
    try {
      let deletedCount = 0;
      let missingCount = 0;

      try {
        const response = await axios.post(`${API}/documents/bulk-delete`, {
          document_ids: selectedDocumentIds,
        });
        deletedCount = response.data?.deleted_count || 0;
        missingCount = response.data?.not_found_ids?.length || 0;
      } catch (bulkError) {
        const status = bulkError?.response?.status;
        const detail = String(bulkError?.response?.data?.detail || "").toLowerCase();
        const shouldFallback =
          status === 404 ||
          status === 405 ||
          detail.includes("method not allowed") ||
          detail.includes("action not allowed");

        if (!shouldFallback) {
          throw bulkError;
        }

        const results = await Promise.allSettled(
          selectedDocumentIds.map((documentId) => axios.delete(`${API}/documents/${documentId}`))
        );
        deletedCount = results.filter((result) => result.status === "fulfilled").length;
        missingCount = results.filter((result) => result.status === "rejected").length;
      }

      toast.success(
        missingCount
          ? `Deleted ${deletedCount} document${deletedCount === 1 ? "" : "s"}. ${missingCount} no longer existed.`
          : `Deleted ${deletedCount} document${deletedCount === 1 ? "" : "s"}.`
      );
      setSelectedDocumentIds([]);
      fetchDocuments();
    } catch (error) {
      console.error("Bulk delete error:", error);
      toast.error(error.response?.data?.detail || "Failed to delete selected documents");
    } finally {
      setIsBulkDeleting(false);
    }
  };

  const previewDocument = async (documentId) => {
    setPreviewLoading(true);
    setPreviewDialogOpen(true);
    try {
      const response = await axios.get(`${API}/documents/${documentId}/chunks?limit=8`);
      setPreviewData(response.data);
    } catch (error) {
      console.error("Preview error:", error);
      setPreviewData(null);
      toast.error(error.response?.data?.detail || "Failed to load chunk preview");
    } finally {
      setPreviewLoading(false);
    }
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const stats = [
    { label: "Total Documents", value: documents.length, icon: FileText },
    { label: "Indexed", value: documents.filter((d) => d.status === "indexed").length, icon: CheckCircle },
    { label: "Processing", value: documents.filter((d) => d.status === "pending" || d.status === "processing").length, icon: Loader2 },
    { label: "Total Chunks", value: documents.reduce((acc, d) => acc + (d.chunk_count || 0), 0), icon: File },
  ];

  const allSelected = documents.length > 0 && selectedDocumentIds.length === documents.length;
  const someSelected = selectedDocumentIds.length > 0 && !allSelected;
  const columnCount = isAdmin ? 8 : 7;

  return (
    <div className="p-4 md:p-6 space-y-6">
      {/* Header */}
      <motion.div 
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
      >
        <div>
          <h1 className="text-2xl font-heading font-bold text-white">
            Document Management
          </h1>
          <p className="text-sm text-[#6b7280] mt-1">
            Upload and manage documents for the knowledge base
          </p>
          {isRefreshing ? (
            <p className="mt-2 text-xs text-[#FFBA00]">Refreshing document status...</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Dialog open={previewDialogOpen} onOpenChange={setPreviewDialogOpen}>
            <DialogContent className="bg-[#1a1e26] border-[#2a3142] max-w-3xl">
              <DialogHeader>
                <DialogTitle className="text-white font-heading">
                  {previewData?.title || "Document chunk preview"}
                </DialogTitle>
              </DialogHeader>
              {previewLoading ? (
                <div className="py-10 flex items-center justify-center">
                  <Loader2 className="w-6 h-6 animate-spin text-[#FFBA00]" />
                </div>
              ) : !previewData ? (
                <p className="text-sm text-[#6b7280]">No preview available.</p>
              ) : (
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="outline" className="bg-[#1e2330] border-[#2a3142] text-[#9ca3af]">
                      {previewData.chunk_count} total chunks
                    </Badge>
                    <Badge variant="outline" className={`${statusColors[previewData.status] || "bg-[#1e2330] text-[#9ca3af] border-[#2a3142]"} border`}>
                      {previewData.status}
                    </Badge>
                  </div>
                  <ScrollArea className="h-[420px] pr-4">
                    <div className="space-y-3">
                      {previewData.chunks?.length ? previewData.chunks.map((chunk) => (
                        <div key={`${previewData.document_id}-${chunk.chunk_index}`} className="rounded-xl border border-[#2a3142] bg-[#12151a] p-4">
                          <p className="text-xs font-mono text-[#FFBA00] mb-2">Chunk {chunk.chunk_index}</p>
                          <p className="text-sm text-[#d1d5db] leading-6 whitespace-pre-wrap">{chunk.chunk_text}</p>
                        </div>
                      )) : (
                        <p className="text-sm text-[#6b7280]">No stored chunks were found for this document.</p>
                      )}
                    </div>
                  </ScrollArea>
                </div>
              )}
            </DialogContent>
          </Dialog>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => fetchDocuments()}
            data-testid="refresh-documents-btn"
            className="text-[#9ca3af] hover:text-white hover:bg-[#1e2330]"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${isRefreshing ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          {isAdmin && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowSettings(!showSettings)}
              data-testid="kb-settings-btn"
              className={`text-[#9ca3af] hover:text-white hover:bg-[#1e2330] ${showSettings ? 'bg-[#1e2330] text-white' : ''}`}
            >
              <Settings className="w-4 h-4 mr-2" />
              KB Settings
            </Button>
          )}
          <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
            <DialogTrigger asChild>
              <Button data-testid="upload-document-btn" className="btn-primary">
                <Upload className="w-4 h-4 mr-2" />
                Add Document
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-[#1a1e26] border-[#2a3142] max-w-lg">
              <DialogHeader>
                <DialogTitle className="text-white font-heading">
                  Add Document
                </DialogTitle>
              </DialogHeader>
              <Tabs defaultValue="file" className="mt-4">
                <TabsList className="bg-[#12151a] w-full border border-[#2a3142]">
                  <TabsTrigger value="file" className="flex-1 data-[state=active]:bg-[#FFBA00] data-[state=active]:text-[#12151a]">
                    <Upload className="w-4 h-4 mr-2" />
                    Upload File
                  </TabsTrigger>
                  <TabsTrigger value="url" className="flex-1 data-[state=active]:bg-[#FFBA00] data-[state=active]:text-[#12151a]">
                    <LinkIcon className="w-4 h-4 mr-2" />
                    Add URL
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="file" className="mt-4 space-y-4">
                  <div
                    className={`upload-zone ${dragOver ? "dragover" : ""}`}
                    onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleDrop}
                    onClick={() => document.getElementById("file-input")?.click()}
                  >
                    <input
                      id="file-input"
                      type="file"
                      className="hidden"
                      accept=".pdf,.docx,.doc,.txt,.csv,.pptx,.ppt"
                      onChange={handleFileSelect}
                    />
                    <Upload className="w-8 h-8 text-[#6b7280] mx-auto mb-2" />
                    {fileUpload.file ? (
                      <p className="text-white font-medium">{fileUpload.file.name}</p>
                    ) : (
                      <>
                        <p className="text-[#9ca3af]">Drop file here or click to browse</p>
                        <p className="text-xs text-[#6b7280] mt-1">Supports PDF, DOCX, TXT, CSV, PPTX</p>
                      </>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label className="text-[#9ca3af]">Title *</Label>
                    <Input
                      value={fileUpload.title}
                      onChange={(e) => setFileUpload({ ...fileUpload, title: e.target.value })}
                      placeholder="Document title"
                      className="input-field"
                      data-testid="file-title-input"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label className="text-[#9ca3af]">Description</Label>
                    <Textarea
                      value={fileUpload.description}
                      onChange={(e) => setFileUpload({ ...fileUpload, description: e.target.value })}
                      placeholder="Optional description"
                      className="input-field"
                      rows={2}
                    />
                  </div>

                  <Button
                    onClick={uploadFile}
                    disabled={isUploading || !fileUpload.file}
                    data-testid="submit-file-upload"
                    className="w-full btn-primary"
                  >
                    {isUploading ? (
                      <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Uploading...</>
                    ) : (
                      <><Upload className="w-4 h-4 mr-2" />Upload Document</>
                    )}
                  </Button>
                </TabsContent>

                <TabsContent value="url" className="mt-4 space-y-4">
                  <div className="space-y-2">
                    <Label className="text-[#9ca3af]">URL *</Label>
                    <Input
                      value={urlUpload.url}
                      onChange={(e) => setUrlUpload({ ...urlUpload, url: e.target.value })}
                      placeholder="https://example.com/page"
                      className="input-field"
                      data-testid="url-input"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label className="text-[#9ca3af]">Title</Label>
                    <Input
                      value={urlUpload.title}
                      onChange={(e) => setUrlUpload({ ...urlUpload, title: e.target.value })}
                      placeholder="Optional custom title"
                      className="input-field"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label className="text-[#9ca3af]">Description</Label>
                    <Textarea
                      value={urlUpload.description}
                      onChange={(e) => setUrlUpload({ ...urlUpload, description: e.target.value })}
                      placeholder="Optional description"
                      className="input-field"
                      rows={2}
                    />
                  </div>

                  <Button
                    onClick={addUrl}
                    disabled={isUploading || !urlUpload.url}
                    data-testid="submit-url"
                    className="w-full btn-primary"
                  >
                    {isUploading ? (
                      <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Adding...</>
                    ) : (
                      <><Globe className="w-4 h-4 mr-2" />Add URL</>
                    )}
                  </Button>
                </TabsContent>
              </Tabs>
            </DialogContent>
          </Dialog>
        </div>
      </motion.div>

      {/* Knowledge Base Settings Panel (Admin only) */}
      <AnimatePresence>
        {showSettings && isAdmin && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <KnowledgeBaseSettings />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
            className="stat-card"
          >
            <div className="flex items-center justify-between">
              <span className="text-[#6b7280] text-sm">{stat.label}</span>
              <stat.icon className="w-4 h-4 text-[#FFBA00]" />
            </div>
            <p className="text-2xl font-heading font-bold text-white mt-2">{stat.value}</p>
          </motion.div>
        ))}
      </div>

      {isAdmin && selectedDocumentIds.length > 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col gap-3 rounded-2xl border border-[#2a3142] bg-[#151922] p-4 md:flex-row md:items-center md:justify-between"
        >
          <div className="flex items-center gap-3 text-sm text-[#d1d5db]">
            <span className="rounded-full bg-[#FFBA00]/10 px-3 py-1 text-[#FFBA00]">
              {selectedDocumentIds.length} selected
            </span>
            <span className="text-[#9ca3af]">Bulk actions apply only to the checked documents.</span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedDocumentIds([])}
              className="text-[#9ca3af] hover:text-white hover:bg-[#1e2330]"
            >
              Clear selection
            </Button>
            <Button
              size="sm"
              onClick={bulkDeleteDocuments}
              disabled={isBulkDeleting}
              className="bg-red-500/90 text-white hover:bg-red-500"
            >
              {isBulkDeleting ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Deleting...</>
              ) : (
                <><Trash2 className="w-4 h-4 mr-2" />Delete selected</>
              )}
            </Button>
          </div>
        </motion.div>
      ) : null}

      {/* Documents table */}
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="card-surface overflow-hidden"
      >
        <ScrollArea className="h-[500px]">
          <Table>
            <TableHeader>
              <TableRow className="border-[#2a3142] hover:bg-transparent">
                {isAdmin ? (
                  <TableHead className="w-12 text-[#9ca3af]">
                    <Checkbox
                      checked={allSelected ? true : someSelected ? "indeterminate" : false}
                      onCheckedChange={(checked) => toggleSelectAll(Boolean(checked))}
                      aria-label="Select all documents"
                      className="border-[#4b5563] data-[state=checked]:bg-[#FFBA00] data-[state=checked]:text-[#12151a]"
                    />
                  </TableHead>
                ) : null}
                <TableHead className="text-[#9ca3af]">Document</TableHead>
                <TableHead className="text-[#9ca3af]">Type</TableHead>
                <TableHead className="text-[#9ca3af]">Size</TableHead>
                <TableHead className="text-[#9ca3af]">Chunks</TableHead>
                <TableHead className="text-[#9ca3af]">Status</TableHead>
                <TableHead className="text-[#9ca3af]">Created</TableHead>
                <TableHead className="text-[#9ca3af] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={columnCount} className="text-center py-8">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#FFBA00]" />
                  </TableCell>
                </TableRow>
              ) : documents.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={columnCount} className="text-center py-8 text-[#6b7280]">
                    No documents yet. Upload your first document to get started.
                  </TableCell>
                </TableRow>
              ) : (
                <AnimatePresence>
                  {documents.map((doc, i) => {
                    const Icon = fileTypeIcons[doc.doc_type] || FileText;
                    const StatusIcon = statusIcons[doc.status] || Clock;
                    return (
                      <motion.tr
                        key={doc.id}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 10 }}
                        transition={{ delay: i * 0.05 }}
                        className="border-[#2a3142] hover:bg-[#1e2330]/50"
                      >
                        {isAdmin ? (
                          <TableCell>
                            <Checkbox
                              checked={selectedDocumentIds.includes(doc.id)}
                              onCheckedChange={(checked) => toggleDocumentSelection(doc.id, Boolean(checked))}
                              aria-label={`Select ${doc.title}`}
                              className="border-[#4b5563] data-[state=checked]:bg-[#FFBA00] data-[state=checked]:text-[#12151a]"
                            />
                          </TableCell>
                        ) : null}
                        <TableCell>
                          <div className="flex items-center gap-3">
                            <div className="w-9 h-9 bg-[#FFBA00]/10 rounded-lg flex items-center justify-center">
                              <Icon className="w-4 h-4 text-[#FFBA00]" />
                            </div>
                            <div>
                              <p className="text-white font-medium truncate max-w-[200px]">{doc.title}</p>
                              {doc.description && (
                                <p className="text-xs text-[#6b7280] truncate max-w-[200px]">{doc.description}</p>
                              )}
                              {doc.status === "failed" && doc.error_message && (
                                <p
                                  className="text-xs text-red-400 max-w-[260px] truncate"
                                  title={doc.error_message}
                                >
                                  {doc.error_message}
                                </p>
                              )}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-[#9ca3af] uppercase text-xs font-mono">{doc.doc_type}</TableCell>
                        <TableCell className="text-[#9ca3af] font-mono text-sm">{formatFileSize(doc.file_size)}</TableCell>
                        <TableCell className="text-[#9ca3af] font-mono">{doc.chunk_count || "-"}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className={`${statusColors[doc.status]} border`}>
                            <StatusIcon className={`w-3 h-3 mr-1 ${doc.status === "processing" ? "animate-spin" : ""}`} />
                            {doc.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-[#9ca3af] text-sm">{formatDate(doc.created_at)}</TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => previewDocument(doc.id)}
                            className="text-[#6b7280] hover:text-white hover:bg-[#1e2330]"
                          >
                            <Eye className="w-4 h-4" />
                          </Button>
                          {isAdmin && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => deleteDocument(doc.id)}
                              data-testid={`delete-doc-${doc.id}`}
                              className="text-[#6b7280] hover:text-red-400 hover:bg-red-500/10"
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          )}
                        </TableCell>
                      </motion.tr>
                    );
                  })}
                </AnimatePresence>
              )}
            </TableBody>
          </Table>
        </ScrollArea>
      </motion.div>
    </div>
  );
}
