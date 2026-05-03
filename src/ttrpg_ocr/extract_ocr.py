from __future__ import annotations
from pathlib import Path
import fitz
from .schemas import BookProfile, Page, Region, RegionType, BBox
from .classify import PageDecision, PageStrategy
from common.pipeline import step

@step("extract_ocr")
def extract_ocr(pdf_path: Path, decisions: list[PageDecision],
                 profile: BookProfile) -> list[Page]:
    targets = {d.page_num for d in decisions if d.strategy == PageStrategy.SCAN_OCR}
    if not targets:
        return []
    raise NotImplementedError("OCR path not yet implemented")