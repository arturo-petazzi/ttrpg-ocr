from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .schemas import BookProfile
from .profiles import load_profile
from .classify import classify_pages, PageStrategy
from .extract_chapters import extract_chapters, ChapterBook
from .extract_ocr import extract_ocr, OcrBook
from common.pipeline import pipeline

log = logging.getLogger(__name__)


@pipeline("process_book")
def process_book(pdf_path: Path, profile: BookProfile,
                 out_dir: Path) -> None:
    decisions = classify_pages(pdf_path, profile)

    has_native = any(d.strategy == PageStrategy.NATIVE_TEXT for d in decisions)
    has_ocr = any(d.strategy == PageStrategy.SCAN_OCR for d in decisions)

    out_dir.mkdir(parents=True, exist_ok=True)

    if has_native:
        chapters: ChapterBook = extract_chapters(pdf_path, decisions, profile)
        out = out_dir / "chapters.json"
        out.write_text(chapters.model_dump_json(indent=2))
        log.info("wrote %s (%d chapters)", out, len(chapters.chapters))

    if has_ocr:
        ocr: OcrBook = extract_ocr(pdf_path, decisions, profile)
        out = out_dir / "ocr_pages.json"
        out.write_text(ocr.model_dump_json(indent=2))
        log.info("wrote %s (%d pages)", out, len(ocr.pages))


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Extract structured text from a TTRPG PDF.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    args = parser.parse_args()

    profile = load_profile(args.profile)
    out_dir = args.out / profile.name
    process_book(args.pdf, profile, out_dir)


if __name__ == "__main__":
    main()
