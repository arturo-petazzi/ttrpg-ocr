from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import fitz
import yaml

from .schemas import BookProfile
from .classify import classify_pages, PageStrategy
from .extract_chapters import (
    _detect_font_tiers,
    extract_chapters,
    ChapterBook,
    NativePage,
    native_page_texts,
)
from .extract_ocr import extract_ocr, OcrChapterBook
from common.pipeline import pipeline

log = logging.getLogger(__name__)


def _load_profile(path: Path) -> BookProfile:
    return BookProfile(**yaml.safe_load(path.open()))


def _flatten_ocr_pages(ocr_book: OcrChapterBook) -> list[dict]:
    pages: list[dict] = []
    for chapter in ocr_book.chapters:
        for page in chapter.pages:
            pages.append({
                "page_num": page.page_num,
                "source": "ocr",
                "text": " ".join(block.text for block in page.blocks).strip(),
                "chapter_title": chapter.title,
            })
    return sorted(pages, key=lambda p: p["page_num"])


def _merge_native_and_ocr(native_book: ChapterBook,
                          native_pages: list[NativePage],
                          ocr_book: OcrChapterBook) -> dict:
    merged = {
        "profile_name": native_book.profile_name,
        "native_chapters": native_book.model_dump(),
        "ocr_chapters": ocr_book.model_dump(),
        "merged_pages": [],
    }

    native_pages_dict = {p.page_num: p for p in native_pages}
    ocr_pages = _flatten_ocr_pages(ocr_book)

    page_nums = sorted(set(list(native_pages_dict) + [p["page_num"] for p in ocr_pages]))
    ocr_pages_dict = {p["page_num"]: p for p in ocr_pages}

    for pn in page_nums:
        if pn in native_pages_dict:
            merged["merged_pages"].append({
                "page_num": pn,
                "source": "native",
                "text": native_pages_dict[pn].text,
            })
        if pn in ocr_pages_dict:
            merged["merged_pages"].append(ocr_pages_dict[pn])

    return merged


@pipeline("process_book")
def process_book(pdf_path: Path, profile: BookProfile,
                 out_dir: Path) -> None:
    decisions = classify_pages(pdf_path, profile)

    has_native = any(d.strategy == PageStrategy.NATIVE_TEXT for d in decisions)
    has_ocr = any(d.strategy == PageStrategy.SCAN_OCR for d in decisions)

    out_dir.mkdir(parents=True, exist_ok=True)

    native_book: ChapterBook | None = None
    ocr_book: OcrChapterBook | None = None
    native_pages: list[NativePage] = []

    if has_native:
        native_book = extract_chapters(pdf_path, decisions, profile)
        with fitz.open(pdf_path) as doc:
            native_page_nums = sorted(
                d.page_num for d in decisions if d.strategy == PageStrategy.NATIVE_TEXT
            )
            tiers = None
            if native_page_nums:
                body, heading_tiers = _detect_font_tiers(doc, native_page_nums)
                tiers = heading_tiers
            if tiers is not None:
                native_pages = native_page_texts(doc, profile, native_page_nums, tiers)

    if has_ocr:
        ocr_book = extract_ocr(pdf_path, decisions, profile)

    if has_native and not has_ocr:
        out = out_dir / "chapters.json"
        out.write_text(native_book.model_dump_json(indent=2))
        log.info("wrote %s (%d chapters)", out, len(native_book.chapters))
    elif has_ocr and not has_native:
        out = out_dir / "chapters.json"
        out.write_text(ocr_book.model_dump_json(indent=2))
        log.info("wrote %s (%d chapters)", out, len(ocr_book.chapters))
    elif has_native and has_ocr:
        merged = _merge_native_and_ocr(native_book, native_pages, ocr_book)

        out = out_dir / "chapters.json"
        out.write_text(json.dumps(merged, indent=2))
        log.info("wrote %s (merged native + ocr output)", out)

        out_native = out_dir / "chapters_native.json"
        out_native.write_text(native_book.model_dump_json(indent=2))
        log.info("wrote %s (%d chapters)", out_native, len(native_book.chapters))

        out_ocr = out_dir / "chapters_ocr.json"
        out_ocr.write_text(ocr_book.model_dump_json(indent=2))
        log.info("wrote %s (%d chapters)", out_ocr, len(ocr_book.chapters))


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Extract structured text from a TTRPG PDF.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    args = parser.parse_args()

    profile = _load_profile(args.profile)
    out_dir = args.out / profile.name
    process_book(args.pdf, profile, out_dir)


if __name__ == "__main__":
    main()
