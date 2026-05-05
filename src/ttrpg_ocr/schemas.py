from enum import Enum
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

class RegionType(str, Enum):
    HEADER = "header"
    TEXT_BODY = "text_body"
    TEXT_SIDEBAR = "text_sidebar"
    TEXT_CAPTION = "text_caption"
    IMAGE = "image"
    FRAME_ORNAMENT = "frame_ornament"

class BBox(BaseModel):
    x: int; y: int; w: int; h: int

class ChapterMarker(BaseModel):
    page: int
    title: str

class BookProfile(BaseModel):
    name: str
    dpi: int = 300
    # layout
    has_header: bool = True
    header_height_pct: float = 0.10  # top 10% of page is header
    has_decorative_frame: bool = False
    column_count: int = 2
    column_gutter_min_px: int = 30
    # image detection
    min_image_area_px: int = 20_000
    image_uniformity_threshold: float = 0.6
    # ocr
    body_psm: int = 6
    sidebar_psm: int = 4
    caption_psm: int = 7
    tesseract_lang: str = "eng"
    # post-processing
    drop_pages: list[int] = Field(default_factory=list)
    chapters: list[ChapterMarker] | None = None  # if set, used instead of font-size detection
    # native text path
    native_text_min_chars: int = Field(default=500, ge=0)
    # The native-text path needs its own column logic too
    native_block_sort: Literal["column_then_y", "y_only"] = "column_then_y"
    enable_ocr: bool = False  # opt-in; default off so old books need explicit profile flag
    native_text_min_chars: int = Field(default=500, ge=0)
    # identify column number
    column_count_max: int = Field(default=2, ge=1, le=4)
    column_gap_min_pct: float = Field(default=0.08, ge=0.01, le=0.3)
    block_width_max_pct: float = Field(default=0.55, ge=0.1, le=1.0)
    mark_images_in_output: bool = True
    min_image_area_px: int = Field(default=5000, ge=0)
    footer_height_pct: float = Field(default=0.05, ge=0.0, le=0.5)

class OcrWord(BaseModel):
    text: str; conf: float; bbox: BBox

class Region(BaseModel):
    type: RegionType
    bbox: BBox
    reading_order: int
    text: str = ""
    words: list[OcrWord] = Field(default_factory=list)

class Page(BaseModel):
    page_num: int
    image_path: Path
    regions: list[Region] = Field(default_factory=list)
    reconstructed_text: str = ""