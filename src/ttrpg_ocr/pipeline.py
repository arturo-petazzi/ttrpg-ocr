from __future__ import annotations
from pathlib import Path
from .schemas import BookProfile, Book
from .profiles import load_profile
from .classify import classify_pages
from .extract_text import extract_text
from .extract_ocr import extract_ocr
from .assemble import assemble_book
from common.pipeline import pipeline

@pipeline("process_book")
def process_book(pdf_path: Path, profile: BookProfile) -> Book:
    decisions = classify_pages(pdf_path, profile)
    native_pages = extract_text(pdf_path, decisions, profile)
    ocr_pages = extract_ocr(pdf_path, decisions, profile)
    return assemble_book(native_pages, ocr_pages, decisions, profile)

def main() -> None:
    import argparse, json, logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    
    profile = load_profile(args.profile)
    book = process_book(args.pdf, profile)
    
    out_dir = args.out / profile.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{profile.name}.json").write_text(book.model_dump_json(indent=2))