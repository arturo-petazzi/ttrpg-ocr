from __future__ import annotations

from enum import Enum
from pathlib import Path

import fitz
from pydantic import BaseModel

from .schemas import BookProfile
from common.pipeline import step


class PageStrategy(str, Enum):
    NATIVE_TEXT = "native_text"
    SKIP = "skip"          # explicit drop or image-only page
    SCAN_OCR = "scan_ocr"  # future: no native text, OCR needed


class PageDecision(BaseModel):
    page_num: int
    strategy: PageStrategy
    reason: str
    text_chars: int


def _classify_one(page: fitz.Page, profile: BookProfile) -> PageDecision:
    n = page.number
    text_chars = len(page.get_text().strip())

    if n in profile.drop_pages:
        return PageDecision(page_num=n, strategy=PageStrategy.SKIP,
                            reason="explicit drop", text_chars=text_chars)

    if text_chars >= profile.native_text_min_chars:
        return PageDecision(page_num=n, strategy=PageStrategy.NATIVE_TEXT,
                            reason="native text", text_chars=text_chars)

    # No native text — OCR stub; skip for now
    return PageDecision(page_num=n, strategy=PageStrategy.SKIP,
                        reason="no native text (OCR not implemented)",
                        text_chars=text_chars)


@step("classify_pages")
def classify_pages(pdf_path: Path, profile: BookProfile) -> list[PageDecision]:
    with fitz.open(pdf_path) as doc:
        return [_classify_one(doc[i], profile) for i in range(len(doc))]
