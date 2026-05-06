from __future__ import annotations

from enum import Enum
from pathlib import Path
import re
import unicodedata

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


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1F\x7F-\x9F]")
_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}")


def _text_looks_corrupt(text: str) -> bool:
    if not text:
        return False

    total = len(text)
    if total < 30:
        return False

    control_count = len(_CONTROL_CHAR_RE.findall(text))
    if control_count / total > 0.03:
        return True

    alpha_count = sum(1 for ch in text if ch.isalpha())
    if alpha_count / total < 0.25:
        return True

    words = _WORD_RE.findall(text)
    if len(words) < 2 and total > 80:
        return True

    return False


def _classify_one(page: fitz.Page, profile: BookProfile) -> PageDecision:
    n = page.number
    text = page.get_text().strip()
    text_chars = len(text)
    corrupt = _text_looks_corrupt(text)

    if n in profile.drop_pages:
        return PageDecision(page_num=n, strategy=PageStrategy.SKIP,
                            reason="explicit drop", text_chars=text_chars)

    if corrupt and profile.enable_ocr:
        return PageDecision(page_num=n, strategy=PageStrategy.SCAN_OCR,
                            reason="corrupt text detected, OCR enabled",
                            text_chars=text_chars)

    if text_chars >= profile.native_text_min_chars:
        return PageDecision(page_num=n, strategy=PageStrategy.NATIVE_TEXT,
                            reason="native text", text_chars=text_chars)

    if profile.enable_ocr:
        return PageDecision(page_num=n, strategy=PageStrategy.SCAN_OCR,
                            reason="no native text, OCR enabled",
                            text_chars=text_chars)

    return PageDecision(page_num=n, strategy=PageStrategy.SKIP,
                        reason="no native text, OCR disabled",
                        text_chars=text_chars)


@step("classify_pages")
def classify_pages(pdf_path: Path, profile: BookProfile) -> list[PageDecision]:
    with fitz.open(pdf_path) as doc:
        return [_classify_one(doc[i], profile) for i in range(len(doc))]
