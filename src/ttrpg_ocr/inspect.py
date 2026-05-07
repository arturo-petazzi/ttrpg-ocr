"""Lightweight PDF inspector — runs before full extraction.
Outputs enough information for Claude Code to write a profile YAML."""

from __future__ import annotations
import json
from pathlib import Path
import fitz
from .schemas import BookProfile

def inspect_pdf(pdf_path: Path, sample_pages: list[int] | None = None) -> dict:
    """Return structural metadata for a PDF without running OCR."""
    doc = fitz.open(pdf_path)
    n_pages = len(doc)

    if sample_pages is None:
        # Sample: first 5, last 5, and evenly spread through the middle
        middle = [int(n_pages * i / 6) for i in range(1, 6)]
        sample_pages = sorted(set([0, 1, 2, 3, 4] + middle +
                                   [n_pages-5, n_pages-4, n_pages-3,
                                    n_pages-2, n_pages-1]))
        sample_pages = [p for p in sample_pages if 0 <= p < n_pages]

    pages = []
    for i in sample_pages:
        page = doc[i]
        text = page.get_text().strip()
        images = page.get_images(full=True)
        pages.append({
            "page": i,
            "text_chars": len(text),
            "image_count": len(images),
            "image_sizes": [(img[2], img[3]) for img in images[:5]],
            "page_size_pts": [page.rect.width, page.rect.height],
            "text_preview": text[:300] if text else "",
        })

    return {
        "path": str(pdf_path),
        "total_pages": n_pages,
        "sample_pages": pages,
    }

def inspect_folder(folder: Path, out_dir: Path) -> None:
    """Inspect all PDFs in a folder and write JSON reports."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(folder.glob("*.pdf")):
        report = inspect_pdf(pdf)
        out = out_dir / f"{pdf.stem}_inspect.json"
        out.write_text(json.dumps(report, indent=2))
        print(f"Inspected: {pdf.name} ({report['total_pages']} pages)")