import pytesseract
from PIL import Image
from pypdf import PdfReader

def extract_text_from_pdf(path: str) -> str:
    reader = PdfReader(path)
    text = []
    for page in reader.pages:
        if page.extract_text():
            text.append(page.extract_text())
    return "\n".join(text)

def extract_text_from_image(path: str) -> str:
    img = Image.open(path)
    return pytesseract.image_to_string(img)
