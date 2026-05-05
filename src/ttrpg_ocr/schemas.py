from __future__ import annotations

from pathlib import Path
from enum import Enum
from pydantic import BaseModel, Field


class ChapterMarker(BaseModel):
    page: int
    title: str


class BookProfile(BaseModel):
    name: str
    header_height_pct: float = Field(default=0.08, ge=0.0, le=0.5)
    footer_height_pct: float = Field(default=0.05, ge=0.0, le=0.5)
    # Pages below this char count are treated as image/non-content pages
    native_text_min_chars: int = Field(default=100, ge=0)
    enable_ocr: bool = False
    ocr_dpi: int = Field(default=300, ge=72, le=600)
    drop_pages: list[int] = Field(default_factory=list)
    chapters: list[ChapterMarker] | None = None


# ── kept for the future OCR pipeline path ────────────────────────────────────

class RegionType(str, Enum):
    TEXT_BODY = "text_body"
    IMAGE = "image"


class BBox(BaseModel):
    x: int; y: int; w: int; h: int


class Region(BaseModel):
    type: RegionType
    bbox: BBox
    reading_order: int
    text: str = ""


class Page(BaseModel):
    page_num: int
    image_path: Path
    regions: list[Region] = Field(default_factory=list)
    reconstructed_text: str = ""
