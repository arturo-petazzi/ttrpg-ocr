from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import fitz
import pandas as pd
import pytesseract
from PIL import Image, ImageEnhance
from pydantic import BaseModel

from .schemas import BookProfile
from .classify import PageDecision, PageStrategy
from common.pipeline import step

log = logging.getLogger(__name__)

# Pages with fewer accepted words than this are treated as full-page illustrations.
_MIN_PAGE_WORDS = 15
# Words below this Tesseract confidence are discarded.
_MIN_WORD_CONF = 30
# Pages where mean confidence of accepted words is below this are full-page images.
_MIN_PAGE_MEAN_CONF = 70


# ── output schema ─────────────────────────────────────────────────────────────

class OcrBlock(BaseModel):
    block_num: int
    text: str
    confidence: float    # mean word confidence for this block, 0-100
    font_size_pt: float  # median word height converted to points; useful for heading detection


class OcrPage(BaseModel):
    page_num: int
    blocks: list[OcrBlock]


class OcrBook(BaseModel):
    profile_name: str
    pages: list[OcrPage]


# ── image helpers ─────────────────────────────────────────────────────────────

def _rasterize(page: fitz.Page, dpi: int) -> Image.Image:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def _crop_margins(img: Image.Image, profile: BookProfile) -> Image.Image:
    w, h = img.size
    top = int(h * profile.header_height_pct)
    bottom = int(h * (1 - profile.footer_height_pct))
    return img.crop((0, top, w, bottom))


def _preprocess(img: Image.Image) -> Image.Image:
    """Grayscale + contrast boost. Helps Tesseract on yellowed/low-contrast scans."""
    gray = img.convert("L")
    return ImageEnhance.Contrast(gray).enhance(2.0)


# ── text cleaning ─────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    # Normalize Unicode: ligatures (ﬁ→fi), curly quotes, em-dashes, etc.
    text = unicodedata.normalize("NFKC", text)
    # Rejoin words hyphenated at line breaks: "direc- tion" → "direction"
    # Only merges when the second part starts lowercase (not a new sentence/proper noun)
    text = re.sub(r"(\w+)-\s+([a-z]\w*)", r"\1\2", text)
    # Collapse leftover whitespace
    return re.sub(r"\s+", " ", text).strip()


# ── OCR and block extraction ──────────────────────────────────────────────────

def _ocr_blocks(img: Image.Image, dpi: int) -> list[OcrBlock] | None:
    """
    Run Tesseract and return blocks, or None if the page looks like a
    full-page illustration (too few accepted words).
    """
    data: pd.DataFrame = pytesseract.image_to_data(
        img, output_type=pytesseract.Output.DATAFRAME
    )
    data = data.dropna(subset=["text"])
    data = data[data["text"].astype(str).str.strip() != ""]
    words = data[data["conf"] >= _MIN_WORD_CONF]

    if len(words) < _MIN_PAGE_WORDS or words["conf"].mean() < _MIN_PAGE_MEAN_CONF:
        return None  # full-page image

    blocks: list[OcrBlock] = []
    for block_num, group in words.groupby("block_num"):
        text = _clean(" ".join(str(t) for t in group["text"].tolist()))
        if not text:
            continue
        median_px = float(group["height"].median())
        blocks.append(OcrBlock(
            block_num=int(block_num),
            text=text,
            confidence=round(float(group["conf"].mean()), 1),
            font_size_pt=round(median_px / dpi * 72, 1),
        ))
    return blocks


def _extract_ocr_one(page: fitz.Page, profile: BookProfile) -> OcrPage | None:
    img = _rasterize(page, profile.ocr_dpi)
    img = _crop_margins(img, profile)
    img = _preprocess(img)
    blocks = _ocr_blocks(img, profile.ocr_dpi)
    if blocks is None:
        log.debug("p%03d: skipped (full-page image or low confidence)", page.number)
        return None
    return OcrPage(page_num=page.number, blocks=blocks)


# ── step ──────────────────────────────────────────────────────────────────────

@step("extract_ocr")
def extract_ocr(pdf_path: Path, decisions: list[PageDecision],
                profile: BookProfile) -> OcrBook:
    targets = sorted(
        d.page_num for d in decisions if d.strategy == PageStrategy.SCAN_OCR
    )
    if not targets:
        return OcrBook(profile_name=profile.name, pages=[])

    pages: list[OcrPage] = []
    with fitz.open(pdf_path) as doc:
        for pn in targets:
            result = _extract_ocr_one(doc[pn], profile)
            if result:
                pages.append(result)
            log.info("p%03d: %s blocks",
                     pn, len(result.blocks) if result else "skipped")

    return OcrBook(profile_name=profile.name, pages=pages)
