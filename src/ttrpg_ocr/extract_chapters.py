from __future__ import annotations

from pathlib import Path
from statistics import mode

import fitz
from pydantic import BaseModel

from .schemas import BookProfile, ChapterMarker
from common.pipeline import step


class SectionEntry(BaseModel):
    title: str
    page_start: int
    text: str


class ChapterEntry(BaseModel):
    title: str
    page_start: int
    sections: list[SectionEntry]


class ChapterBook(BaseModel):
    profile_name: str
    chapters: list[ChapterEntry]


# ── helpers ──────────────────────────────────────────────────────────────────

def _detect_body_size(doc: fitz.Document, drop: set[int], sample: int = 10) -> float:
    sizes: list[int] = []
    checked = 0
    for i in range(len(doc)):
        if i in drop or checked >= sample:
            continue
        for block in doc[i].get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        sizes.append(round(span["size"] * 2) / 2)
        checked += 1
    return mode(sizes) if sizes else 9.0


def _is_section_heading(size: float, body: float, text: str) -> bool:
    """True if this span looks like a section heading (not body, not page number)."""
    if text.strip().isdigit():
        return False
    return size / body >= 1.25


def _page_sections(page: fitz.Page, profile: BookProfile,
                   body_size: float) -> list[tuple[str, str]]:
    """
    Extract (kind, text) pairs from one page, where kind is 'heading' or 'body'.
    Header/footer strips are excluded.
    """
    h = page.rect.height
    header_y = h * profile.header_height_pct
    footer_y = h * (1 - profile.footer_height_pct)

    result: list[tuple[str, str]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        if block["bbox"][1] < header_y or block["bbox"][3] > footer_y:
            continue
        for line in block["lines"]:
            line_text = "".join(s["text"] for s in line["spans"]).strip()
            if not line_text or line_text.isdigit():
                continue
            sizes = [s["size"] for s in line["spans"] if s["text"].strip()]
            if not sizes:
                continue
            if _is_section_heading(max(sizes), body_size, line_text):
                result.append(("heading", line_text))
            else:
                result.append(("body", line_text))
    return result


def _build_sections(spans: list[tuple[str, str]]) -> list[SectionEntry]:
    """Group (heading, body) spans into SectionEntry list."""
    sections: list[list] = []  # [title, page_start, [body_fragments]]
    for kind, text in spans:
        if kind == "heading":
            sections.append([text, 0, []])
        else:
            if not sections:
                sections.append(["(Introduction)", 0, []])
            sections[-1][2].append(text)

    return [
        SectionEntry(title=s[0], page_start=s[1], text=" ".join(s[2]).strip())
        for s in sections
        if s[2]
    ]


# ── main paths ────────────────────────────────────────────────────────────────

def _extract_with_manual_chapters(doc: fitz.Document, profile: BookProfile,
                                  body_size: float) -> list[ChapterEntry]:
    markers: list[ChapterMarker] = sorted(profile.chapters, key=lambda c: c.page)
    drop = set(profile.drop_pages)

    # Build page → chapter index
    chapter_pages: list[list[int]] = [[] for _ in markers]
    for page_num in range(len(doc)):
        if page_num in drop:
            continue
        # Assign page to the last chapter whose start <= page_num
        idx = None
        for i, m in enumerate(markers):
            if page_num >= m.page:
                idx = i
        if idx is not None:
            chapter_pages[idx].append(page_num)

    chapters: list[ChapterEntry] = []
    for marker, pages in zip(markers, chapter_pages):
        all_spans: list[tuple[str, str]] = []
        for pn in pages:
            all_spans.extend(_page_sections(doc[pn], profile, body_size))

        sections = _build_sections(all_spans)
        if sections:
            chapters.append(ChapterEntry(
                title=marker.title,
                page_start=marker.page,
                sections=sections,
            ))

    return chapters


def _extract_auto_chapters(doc: fitz.Document, profile: BookProfile,
                            body_size: float) -> list[ChapterEntry]:
    """Fallback: treat the largest embedded headings as chapter titles."""
    drop = set(profile.drop_pages)
    all_spans: list[tuple[str, str]] = []
    for i in range(len(doc)):
        if i in drop:
            continue
        all_spans.extend(_page_sections(doc[i], profile, body_size))

    # Treat headings as sections; wrap everything in a single unnamed chapter
    sections = _build_sections(all_spans)
    if not sections:
        return []
    return [ChapterEntry(title="(Auto)", page_start=0, sections=sections)]


# ── step ──────────────────────────────────────────────────────────────────────

@step("extract_chapters")
def extract_chapters(pdf_path: Path, profile: BookProfile) -> ChapterBook:
    drop = set(profile.drop_pages)
    with fitz.open(pdf_path) as doc:
        body_size = _detect_body_size(doc, drop)
        if profile.chapters:
            chapters = _extract_with_manual_chapters(doc, profile, body_size)
        else:
            chapters = _extract_auto_chapters(doc, profile, body_size)

    return ChapterBook(profile_name=profile.name, chapters=chapters)
