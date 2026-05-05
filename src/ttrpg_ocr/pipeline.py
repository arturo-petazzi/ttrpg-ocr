from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .schemas import BookProfile
from .profiles import load_profile
from .classify import classify_pages
from .extract_chapters import extract_chapters, ChapterBook
from common.pipeline import pipeline


@pipeline("process_book")
def process_book(pdf_path: Path, profile: BookProfile) -> ChapterBook:
    decisions = classify_pages(pdf_path, profile)
    return extract_chapters(pdf_path, decisions, profile)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Extract structured text from a TTRPG PDF.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    args = parser.parse_args()

    profile = load_profile(args.profile)
    book = process_book(args.pdf, profile)

    out_dir = args.out / profile.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "chapters.json"
    out_file.write_text(book.model_dump_json(indent=2))
    logging.getLogger(__name__).info("wrote %s", out_file)
