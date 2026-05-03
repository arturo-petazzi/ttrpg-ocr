from enum import Enum

class PageStrategy(str, Enum):
    NATIVE_TEXT = "native_text"
    SCAN_OCR = "scan_ocr"

def classify_page(page: fitz.Page, profile: BookProfile) -> PageStrategy:
    text_chars = len(page.get_text().strip())
    if text_chars >= profile.native_text_min_chars:
        return PageStrategy.NATIVE_TEXT
    return PageStrategy.SCAN_OCR