"""Document processing for different file types"""
import os
import re
import logging
import shutil
from typing import List, Dict, Optional
from io import BytesIO
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Process different document types and extract text"""
    
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200

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
            
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            
            full_text = cls.clean_text("\n".join(text_parts))
            used_ocr = False

            if not full_text.strip():
                ocr_result = cls.ocr_pdf(file_content)
                if not ocr_result["success"]:
                    return ocr_result
                full_text = cls.clean_text(ocr_result["text"])
                used_ocr = True

            chunks = cls.chunk_text(full_text)
            
            return {
                "success": True,
                "text": full_text,
                "chunks": chunks,
                "page_count": len(reader.pages),
                "used_ocr": used_ocr
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
    def ocr_pdf(cls, file_content: bytes) -> Dict:
        """Run OCR on scanned PDFs that do not contain a text layer."""
        tesseract_cmd = cls._resolve_tesseract_command()
        try:
            import fitz
            from PIL import Image
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

            for page_number, page in enumerate(pdf, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.open(BytesIO(pix.tobytes("png")))
                if pytesseract:
                    page_text = pytesseract.image_to_string(image)
                else:
                    import numpy as np
                    ocr_result, _ = rapid_ocr(np.array(image))
                    page_text = "\n".join(item[1] for item in ocr_result) if ocr_result else ""
                cleaned = cls.clean_text(page_text)
                if cleaned:
                    text_parts.append(f"Page {page_number}\n{cleaned}")

            full_text = cls.clean_text("\n\n".join(text_parts))
            chunks = cls.chunk_text(full_text)

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
                "ocr_engine": "tesseract" if ocr_with_tesseract else "rapidocr"
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
