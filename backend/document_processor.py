"""Document processing for different file types"""
import os
import re
import logging
import shutil
from typing import List, Dict, Optional, Tuple
from io import BytesIO
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Process different document types and extract text"""
    
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200

    @classmethod
    def _chunk_settings(
        cls,
        *,
        file_size_bytes: int = 0,
        page_count: int = 0,
        used_ocr: bool = False,
        text_length: int = 0,
    ) -> Tuple[int, int]:
        """Use larger chunks for very large documents to reduce embedding load."""
        size_mb = max(file_size_bytes / (1024 * 1024), 0.0)

        chunk_size = cls.CHUNK_SIZE
        overlap = cls.CHUNK_OVERLAP

        if text_length >= 500_000 or page_count >= 60 or size_mb >= 15:
            chunk_size = 1600
            overlap = 240
        if used_ocr or text_length >= 1_000_000 or page_count >= 120 or size_mb >= 30:
            chunk_size = 2200
            overlap = 260
        if text_length >= 2_000_000 or page_count >= 180 or size_mb >= 45:
            chunk_size = 2800
            overlap = 320
        if used_ocr and (text_length >= 3_000_000 or page_count >= 240 or size_mb >= 60):
            chunk_size = 3600
            overlap = 360

        return chunk_size, overlap

    @staticmethod
    def _ocr_render_scale(page_count: int, file_size_bytes: int) -> float:
        """Reduce OCR image resolution for very large scanned PDFs to avoid timeouts."""
        size_mb = max(file_size_bytes / (1024 * 1024), 0.0)
        if page_count >= 150 or size_mb >= 60:
            return 1.0
        if page_count >= 100 or size_mb >= 40:
            return 1.15
        if page_count >= 60 or size_mb >= 25:
            return 1.3
        if page_count >= 25 or size_mb >= 10:
            return 1.55
        return 2.0

    @staticmethod
    def _resolve_tesseract_command() -> Optional[str]:
        """Resolve the Tesseract executable for OCR."""
        configured = os.environ.get("TESSERACT_CMD")
        if configured and os.path.exists(configured):
            return configured

        return shutil.which("tesseract")
    
    @staticmethod
    def clean_text(text: str) -> str:
        """Clean and normalize extracted text"""
        # Remove multiple newlines and spaces
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r' +', ' ', text)
        text = text.strip()
        return text

    @classmethod
    def clean_ocr_text(cls, text: str) -> str:
        """Normalize OCR-heavy text while keeping useful structure."""
        if not text:
            return ""

        text = text.replace("\x0c", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
        text = re.sub(r"(?<=\w)\s*\n\s*(?=\w)", " ", text)
        text = re.sub(r"[|]{2,}", "|", text)
        text = re.sub(r"[_]{2,}", "_", text)

        cleaned_lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            alnum_count = sum(char.isalnum() for char in line)
            if alnum_count == 0:
                continue

            symbol_count = sum(not char.isalnum() and not char.isspace() for char in line)
            if len(line) >= 8 and (symbol_count / max(len(line), 1)) > 0.45:
                continue

            cleaned_lines.append(line)

        return cls.clean_text("\n".join(cleaned_lines))

    @staticmethod
    def _text_quality_metrics(text: str) -> Dict[str, float]:
        """Estimate extraction quality for OCR or weak PDF text."""
        normalized = (text or "").strip()
        if not normalized:
            return {
                "quality_score": 0.0,
                "word_count": 0,
                "alpha_ratio": 0.0,
                "digit_ratio": 0.0,
                "noise_ratio": 1.0,
                "avg_word_length": 0.0,
            }

        letters = sum(char.isalpha() for char in normalized)
        digits = sum(char.isdigit() for char in normalized)
        spaces = sum(char.isspace() for char in normalized)
        total_chars = len(normalized)
        noise_chars = max(total_chars - letters - digits - spaces, 0)

        words = re.findall(r"\b[\w/-]+\b", normalized)
        word_count = len(words)
        avg_word_length = (
            sum(len(word) for word in words) / word_count
            if word_count
            else 0.0
        )

        alpha_ratio = letters / total_chars
        digit_ratio = digits / total_chars
        noise_ratio = noise_chars / total_chars

        score = 0.0
        if word_count >= 20:
            score += 0.35
        elif word_count >= 8:
            score += 0.2
        else:
            score += 0.08

        score += min(alpha_ratio, 0.55)
        score += max(0.0, 0.18 - noise_ratio)
        if 2.5 <= avg_word_length <= 12:
            score += 0.08
        if digit_ratio > 0.35:
            score -= 0.08

        return {
            "quality_score": round(max(0.0, min(score, 1.0)), 3),
            "word_count": word_count,
            "alpha_ratio": round(alpha_ratio, 3),
            "digit_ratio": round(digit_ratio, 3),
            "noise_ratio": round(noise_ratio, 3),
            "avg_word_length": round(avg_word_length, 3),
        }

    @classmethod
    def _should_force_ocr(cls, extracted_text: str, page_count: int) -> bool:
        """Decide when a PDF text layer is too weak and OCR should be attempted."""
        metrics = cls._text_quality_metrics(extracted_text)
        if metrics["word_count"] == 0:
            return True
        if page_count >= 2 and metrics["word_count"] < page_count * 25:
            return True
        return metrics["quality_score"] < 0.32

    @staticmethod
    def _merge_text_versions(primary_text: str, secondary_text: str) -> Tuple[str, Dict[str, float]]:
        """Choose the cleaner text version using quality metrics."""
        primary_metrics = DocumentProcessor._text_quality_metrics(primary_text)
        secondary_metrics = DocumentProcessor._text_quality_metrics(secondary_text)

        if secondary_metrics["quality_score"] > primary_metrics["quality_score"] + 0.08:
            return secondary_text, secondary_metrics
        return primary_text, primary_metrics
    
    @staticmethod
    def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """Split text into overlapping chunks"""
        if not text:
            return []
        
        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= chunk_size:
                current_chunk += " " + sentence if current_chunk else sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    # Keep some overlap
                    words = current_chunk.split()
                    overlap_words = words[-overlap//5:] if len(words) > overlap//5 else words
                    current_chunk = " ".join(overlap_words) + " " + sentence
                else:
                    # Sentence is too long, split by words
                    words = sentence.split()
                    for i in range(0, len(words), chunk_size//5):
                        chunk_words = words[i:i + chunk_size//5]
                        chunks.append(" ".join(chunk_words))
                    current_chunk = ""
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    @classmethod
    def process_pdf(cls, file_content: bytes) -> Dict:
        """Extract text from PDF file"""
        try:
            try:
                from pypdf import PdfReader
            except ImportError:
                from PyPDF2 import PdfReader
            
            reader = PdfReader(BytesIO(file_content))
            text_parts = []
            page_texts = []
            
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    cleaned_page = cls.clean_text(page_text)
                    page_texts.append(cleaned_page)
                    if cleaned_page:
                        text_parts.append(cleaned_page)
                else:
                    page_texts.append("")
            
            extracted_text = cls.clean_text("\n".join(text_parts))
            used_ocr = False
            ocr_engine = None

            if not extracted_text.strip() or cls._should_force_ocr(extracted_text, len(reader.pages)):
                ocr_result = cls.ocr_pdf(file_content, extracted_pages=page_texts)
                if not ocr_result["success"]:
                    if not extracted_text.strip():
                        return ocr_result
                    full_text = extracted_text
                    quality_metrics = cls._text_quality_metrics(full_text)
                else:
                    merged_text, quality_metrics = cls._merge_text_versions(
                        extracted_text,
                        cls.clean_ocr_text(ocr_result["text"]),
                    )
                    full_text = cls.clean_text(merged_text)
                    used_ocr = True
                    ocr_engine = ocr_result.get("ocr_engine")
            else:
                full_text = extracted_text
                quality_metrics = cls._text_quality_metrics(full_text)

            chunk_size, overlap = cls._chunk_settings(
                file_size_bytes=len(file_content),
                page_count=len(reader.pages),
                used_ocr=used_ocr,
                text_length=len(full_text),
            )
            chunks = cls.chunk_text(full_text, chunk_size=chunk_size, overlap=overlap)
            
            return {
                "success": True,
                "text": full_text,
                "chunks": chunks,
                "page_count": len(reader.pages),
                "used_ocr": used_ocr,
                "ocr_engine": ocr_engine,
                "ocr_quality_score": quality_metrics.get("quality_score", 0.0),
                "extraction_quality": quality_metrics,
                "chunk_size": chunk_size,
            }
        except ImportError:
            logger.error("PDF support is unavailable because no PDF reader library is installed")
            return {
                "success": False,
                "error": "PDF support is not installed on the backend yet. Please install the PDF reader dependency.",
                "chunks": []
            }
        except Exception as e:
            logger.error(f"Error processing PDF: {e}")
            return {"success": False, "error": str(e), "chunks": []}

    @classmethod
    def ocr_pdf(cls, file_content: bytes, extracted_pages: Optional[List[str]] = None) -> Dict:
        """Run OCR on scanned PDFs that do not contain a text layer."""
        tesseract_cmd = cls._resolve_tesseract_command()
        try:
            import fitz
            from PIL import Image, ImageFilter, ImageOps
        except ImportError as exc:
            logger.error("OCR dependencies missing: %s", exc)
            return {
                "success": False,
                "error": "OCR dependencies are not installed on the backend yet.",
                "chunks": []
            }

        try:
            pdf = fitz.open(stream=file_content, filetype="pdf")
            text_parts = []

            ocr_with_tesseract = False
            pytesseract = None
            rapid_ocr = None

            if tesseract_cmd:
                try:
                    import pytesseract as pytesseract_module
                    pytesseract_module.pytesseract.tesseract_cmd = tesseract_cmd
                    pytesseract = pytesseract_module
                    ocr_with_tesseract = True
                except Exception as exc:
                    logger.warning("Tesseract OCR unavailable, falling back to RapidOCR: %s", exc)

            if not pytesseract:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                    rapid_ocr = RapidOCR()
                except Exception as exc:
                    logger.error("RapidOCR unavailable: %s", exc)
                    return {
                        "success": False,
                        "error": (
                            "This PDF appears to be scanned, but no OCR engine is available on the backend."
                        ),
                        "chunks": []
                    }

            render_scale = cls._ocr_render_scale(pdf.page_count, len(file_content))

            for page_number, page in enumerate(pdf, start=1):
                extracted_page_text = ""
                if extracted_pages and len(extracted_pages) >= page_number:
                    extracted_page_text = cls.clean_text(extracted_pages[page_number - 1] or "")

                extracted_metrics = cls._text_quality_metrics(extracted_page_text)
                needs_ocr = (
                    not extracted_page_text
                    or extracted_metrics["word_count"] < 12
                    or extracted_metrics["quality_score"] < 0.22
                )

                if not needs_ocr:
                    text_parts.append(f"Page {page_number}\n{extracted_page_text}")
                    continue

                pix = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
                image = Image.open(BytesIO(pix.tobytes("png")))
                image = ImageOps.grayscale(image)
                image = ImageOps.autocontrast(image)
                image = image.filter(ImageFilter.SHARPEN)
                if pytesseract:
                    page_text = pytesseract.image_to_string(image, config="--psm 6")
                else:
                    import numpy as np
                    ocr_result, _ = rapid_ocr(np.array(image))
                    page_text = "\n".join(item[1] for item in ocr_result) if ocr_result else ""
                cleaned = cls.clean_ocr_text(page_text)
                if cleaned:
                    text_parts.append(f"Page {page_number}\n{cleaned}")

            full_text = cls.clean_text("\n\n".join(text_parts))
            chunk_size, overlap = cls._chunk_settings(
                file_size_bytes=len(file_content),
                page_count=pdf.page_count,
                used_ocr=True,
                text_length=len(full_text),
            )
            chunks = cls.chunk_text(full_text, chunk_size=chunk_size, overlap=overlap)
            quality_metrics = cls._text_quality_metrics(full_text)

            if not chunks:
                return {
                    "success": False,
                    "error": "OCR ran, but no readable text could be recognized from this scanned PDF.",
                    "chunks": []
                }

            return {
                "success": True,
                "text": full_text,
                "chunks": chunks,
                "used_ocr": True,
                "ocr_engine": "tesseract" if ocr_with_tesseract else "rapidocr",
                "ocr_quality_score": quality_metrics.get("quality_score", 0.0),
                "extraction_quality": quality_metrics,
                "chunk_size": chunk_size,
            }
        except Exception as exc:
            logger.error("OCR processing failed: %s", exc)
            return {
                "success": False,
                "error": f"OCR failed while processing the scanned PDF: {exc}",
                "chunks": []
            }
    
    @classmethod
    def process_docx(cls, file_content: bytes) -> Dict:
        """Extract text from DOCX file"""
        try:
            from docx import Document
            
            doc = Document(BytesIO(file_content))
            text_parts = []
            
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
            
            # Also extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        text_parts.append(row_text)
            
            full_text = cls.clean_text("\n".join(text_parts))
            chunks = cls.chunk_text(full_text)
            
            return {
                "success": True,
                "text": full_text,
                "chunks": chunks,
                "paragraph_count": len(doc.paragraphs)
            }
        except Exception as e:
            logger.error(f"Error processing DOCX: {e}")
            return {"success": False, "error": str(e), "chunks": []}
    
    @classmethod
    def process_txt(cls, file_content: bytes) -> Dict:
        """Extract text from TXT file"""
        try:
            # Try different encodings
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    text = file_content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = file_content.decode('utf-8', errors='ignore')
            
            full_text = cls.clean_text(text)
            chunks = cls.chunk_text(full_text)
            
            return {
                "success": True,
                "text": full_text,
                "chunks": chunks
            }
        except Exception as e:
            logger.error(f"Error processing TXT: {e}")
            return {"success": False, "error": str(e), "chunks": []}
    
    @classmethod
    def process_csv(cls, file_content: bytes) -> Dict:
        """Extract text from CSV file"""
        try:
            import csv
            from io import StringIO
            
            # Decode content
            text = file_content.decode('utf-8', errors='ignore')
            reader = csv.reader(StringIO(text))
            
            rows = []
            headers = None
            for i, row in enumerate(reader):
                if i == 0:
                    headers = row
                    rows.append(" | ".join(row))
                else:
                    # Create key-value pairs for better context
                    if headers:
                        row_text = ", ".join(f"{h}: {v}" for h, v in zip(headers, row) if v.strip())
                    else:
                        row_text = " | ".join(row)
                    if row_text:
                        rows.append(row_text)
            
            full_text = cls.clean_text("\n".join(rows))
            chunks = cls.chunk_text(full_text)
            
            return {
                "success": True,
                "text": full_text,
                "chunks": chunks,
                "row_count": len(rows)
            }
        except Exception as e:
            logger.error(f"Error processing CSV: {e}")
            return {"success": False, "error": str(e), "chunks": []}
    
    @classmethod
    def process_pptx(cls, file_content: bytes) -> Dict:
        """Extract text from PPTX file"""
        try:
            from pptx import Presentation
            
            prs = Presentation(BytesIO(file_content))
            text_parts = []
            
            for slide_num, slide in enumerate(prs.slides, 1):
                slide_texts = [f"Slide {slide_num}:"]
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_texts.append(shape.text)
                    elif hasattr(shape, "table"):
                        for row in shape.table.rows:
                            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                            if row_text:
                                slide_texts.append(row_text)
                
                if len(slide_texts) > 1:
                    text_parts.append("\n".join(slide_texts))
            
            full_text = cls.clean_text("\n\n".join(text_parts))
            chunks = cls.chunk_text(full_text)
            
            return {
                "success": True,
                "text": full_text,
                "chunks": chunks,
                "slide_count": len(prs.slides)
            }
        except Exception as e:
            logger.error(f"Error processing PPTX: {e}")
            return {"success": False, "error": str(e), "chunks": []}
    
    @classmethod
    async def process_url(cls, url: str) -> Dict:
        """Scrape and extract text from a URL"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'lxml')
                
                # Remove script and style elements
                for script in soup(["script", "style", "nav", "footer", "header"]):
                    script.decompose()
                
                # Get text from main content areas
                main_content = soup.find(['main', 'article']) or soup.find('body')
                
                if main_content:
                    # Extract paragraphs and headings
                    text_parts = []
                    for element in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'td']):
                        text = element.get_text(strip=True)
                        if text and len(text) > 10:
                            text_parts.append(text)
                    
                    full_text = cls.clean_text("\n".join(text_parts))
                else:
                    full_text = cls.clean_text(soup.get_text())
                
                chunks = cls.chunk_text(full_text)
                
                # Get title
                title = soup.find('title')
                title_text = title.get_text(strip=True) if title else url
                
                return {
                    "success": True,
                    "text": full_text,
                    "chunks": chunks,
                    "title": title_text,
                    "url": url
                }
        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}")
            return {"success": False, "error": str(e), "chunks": []}
    
    @classmethod
    def process_file(cls, file_content: bytes, file_type: str) -> Dict:
        """Process file based on type"""
        processors = {
            "pdf": cls.process_pdf,
            "docx": cls.process_docx,
            "txt": cls.process_txt,
            "csv": cls.process_csv,
            "pptx": cls.process_pptx,
        }
        
        processor = processors.get(file_type.lower())
        if not processor:
            return {"success": False, "error": f"Unsupported file type: {file_type}", "chunks": []}
        
        result = processor(file_content)
        if result.get("success") and not result.get("chunks"):
            return {
                "success": False,
                "error": "No readable text could be extracted from this file.",
                "chunks": []
            }

        return result
