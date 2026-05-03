from __future__ import annotations
from enum import Enum
from pathlib import Path
import fitz
from pydantic import BaseModel
from .schemas import BookProfile
from common.pipeline import step

class PageStrategy(str, Enum):
    NATIVE_TEXT = "native_text"
    SCAN_OCR = "scan_ocr"
    SKIP = "skip"

class PageDecision(BaseModel):
    page_num: int
    strategy: PageStrategy
    reason: str  # human-readable: "explicit drop", "no text + ocr disabled", etc.
    text_chars: int
    image_count: int

def _classify_one(page: fitz.Page, profile: BookProfile) -> PageDecision:
    n = page.number
    text_chars = len(page.get_text().strip())
    image_count = len(page.get_images(full=True))

    if n in profile.drop_pages:
        return PageDecision(page_num=n, strategy=PageStrategy.SKIP,
                            reason="explicit drop", text_chars=text_chars,
                            image_count=image_count)

    if text_chars >= profile.native_text_min_chars:
        return PageDecision(page_num=n, strategy=PageStrategy.NATIVE_TEXT,
                            reason="native text present", text_chars=text_chars,
                            image_count=image_count)

    if profile.enable_ocr:
        return PageDecision(page_num=n, strategy=PageStrategy.SCAN_OCR,
                            reason="no native text, ocr enabled",
                            text_chars=text_chars, image_count=image_count)

    return PageDecision(page_num=n, strategy=PageStrategy.SKIP,
                        reason="no native text, ocr disabled",
                        text_chars=text_chars, image_count=image_count)

@step("classify_pages")
def classify_pages(pdf_path: Path, profile: BookProfile) -> list[PageDecision]:
    with fitz.open(pdf_path) as doc:
        return [_classify_one(doc[i], profile) for i in range(len(doc))]