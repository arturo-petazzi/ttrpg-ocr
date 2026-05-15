from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mode

import fitz
from pydantic import BaseModel, Field

from .schemas import BookProfile, ChapterMarker
from .classify import PageDecision, PageStrategy
from common.pipeline import step


# ── output schema ─────────────────────────────────────────────────────────────

class SectionSpan(BaseModel):
    page_num: int
    text: str


class SectionEntry(BaseModel):
    title: str
    page_start: int
    text: str                                    # joined string; kept for backwards compat
    spans: list[SectionSpan] = Field(default_factory=list)


class ChapterEntry(BaseModel):
    title: str
    page_start: int
    sections: list[SectionEntry]


class ChapterBook(BaseModel):
    profile_name: str
    chapters: list[ChapterEntry]

class NativePage(BaseModel):
    page_num: int
    text: str

# ── font-tier detection ────────────────────────────────────────────────────────

def _detect_font_tiers(doc: fitz.Document, native_pages: list[int],
                        sample: int = 20) -> tuple[float, list[float]]:
    """
    Scan up to `sample` native pages and return (body_size, heading_tiers).

    heading_tiers is a list of minimum font sizes for each tier, sorted
    descending (largest heading first). Tiers are clusters of sizes that are
    > body + 1pt and appear on at least 2 lines.
    """
    line_sizes: list[float] = []

    for i, pn in enumerate(native_pages):
        if i >= sample:
            break
        for block in doc[pn].get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                text = "".join(s["text"] for s in line["spans"]).strip()
                if not text or text.isdigit():
                    continue
                sizes = [s["size"] for s in line["spans"] if s["text"].strip()]
                if sizes:
                    # Round to nearest 0.5pt to collapse near-identical sizes
                    line_sizes.append(round(max(sizes) * 2) / 2)

    if not line_sizes:
        return 9.0, []

    body = mode(line_sizes)

    # Sizes that appear on ≥2 lines and are clearly above body
    counter = Counter(line_sizes)
    above = sorted(s for s, c in counter.items() if s > body + 1.0 and c >= 2)

    if not above:
        return body, []

    # Cluster consecutive sizes within 0.5pt of each other into tiers.
    # Each tier is represented by its minimum (= detection threshold).
    tiers: list[float] = []
    cluster = [above[0]]
    for s in above[1:]:
        if s - cluster[-1] > 0.5:
            tiers.append(min(cluster))
            cluster = [s]
        else:
            cluster.append(s)
    tiers.append(min(cluster))

    return body, sorted(tiers, reverse=True)  # largest heading tier first


def _span_tier(size: float, tiers: list[float], tolerance: float = 0.4) -> int | None:
    """
    Return the tier index (0 = largest/most important) if size matches a tier,
    else None (body text).
    """
    for i, threshold in enumerate(tiers):
        if size >= threshold - tolerance:
            return i
    return None


# ── column detection ──────────────────────────────────────────────────────────

def _detect_column_count(x_centers: list[float], page_width: float,
                          max_cols: int, gap_min_pct: float) -> int:
    """Count columns by finding large x-gaps between sorted block centers."""
    if len(x_centers) < 4:
        return 1
    sorted_x = sorted(x_centers)
    min_gap = gap_min_pct * page_width
    n_gaps = sum(
        1 for i in range(len(sorted_x) - 1)
        if sorted_x[i + 1] - sorted_x[i] >= min_gap
    )
    return min(n_gaps + 1, max_cols)


def _assign_columns(x_centers: list[float], n_cols: int) -> list[int]:
    """Assign a column index (0-based) to each x_center using the n_cols-1 largest gaps."""
    if n_cols == 1:
        return [0] * len(x_centers)
    sorted_x = sorted(x_centers)
    gaps = sorted(
        ((sorted_x[i + 1] - sorted_x[i], (sorted_x[i] + sorted_x[i + 1]) / 2)
         for i in range(len(sorted_x) - 1)),
        reverse=True,
    )
    boundaries = sorted(mid for _, mid in gaps[: n_cols - 1])
    return [sum(1 for b in boundaries if x >= b) for x in x_centers]


# ── page text extraction ───────────────────────────────────────────────────────

def _page_spans(page: fitz.Page, profile: BookProfile,
                tiers: list[float]) -> list[tuple[int | None, str, int]]:
    """
    Return (tier_index, text, page_num) for each line on the page.
    tier_index=None means body text. Page numbers and empty lines are dropped.
    Header/footer strips are excluded. Blocks are sorted left-column-first.
    """
    h = page.rect.height
    header_y = h * profile.header_height_pct
    footer_y = h * (1 - profile.footer_height_pct)
    pn = page.number

    blocks = [
        b for b in page.get_text("dict")["blocks"]
        if b.get("type") == 0
        and b["bbox"][1] >= header_y
        and b["bbox"][3] <= footer_y
    ]

    if len(blocks) >= 4:
        page_width = page.rect.width
        x_centers = [(b["bbox"][0] + b["bbox"][2]) / 2 for b in blocks]
        n_cols = _detect_column_count(
            x_centers, page_width, profile.column_count_max, profile.column_gap_min_pct
        )
        col_indices = _assign_columns(x_centers, n_cols)
        order = sorted(range(len(blocks)),
                       key=lambda i: (col_indices[i], blocks[i]["bbox"][1]))
        blocks = [blocks[i] for i in order]

    result = []
    for block in blocks:
        for line in block["lines"]:
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text or text.isdigit():
                continue
            sizes = [s["size"] for s in line["spans"] if s["text"].strip()]
            if not sizes:
                continue
            tier = _span_tier(max(sizes), tiers)
            result.append((tier, text, pn))

    return result


# ── section grouping ───────────────────────────────────────────────────────────

def _build_sections(spans: list[tuple[int | None, str, int]]) -> list[SectionEntry]:
    """Group (tier, text, page) spans into SectionEntry list."""
    sections: list[list] = []  # [title, page_start, [body_texts], [(page_num, text)]]

    for tier, text, pn in spans:
        if tier is not None:
            sections.append([text, pn, [], []])
        else:
            if not sections:
                sections.append(["(Introduction)", pn, [], []])
            sections[-1][2].append(text)
            sections[-1][3].append((pn, text))

    return [
        SectionEntry(
            title=s[0],
            page_start=s[1],
            text=" ".join(s[2]).strip(),
            spans=[SectionSpan(page_num=pn, text=t) for pn, t in s[3]],
        )
        for s in sections
        if s[2]
    ]


# ── extraction paths ──────────────────────────────────────────────────────────

def _extract_with_manual_chapters(doc: fitz.Document, profile: BookProfile,
                                   native_pages: list[int],
                                   tiers: list[float]) -> list[ChapterEntry]:
    markers = sorted(profile.chapters, key=lambda c: c.page)
    native_set = set(native_pages)

    # Map each native page to its chapter index
    chapter_pages: list[list[int]] = [[] for _ in markers]
    for pn in native_pages:
        idx = None
        for i, m in enumerate(markers):
            if pn >= m.page:
                idx = i
        if idx is not None:
            chapter_pages[idx].append(pn)

    chapters = []
    for marker, pages in zip(markers, chapter_pages):
        spans: list[tuple[int | None, str, int]] = []
        for pn in pages:
            spans.extend(_page_spans(doc[pn], profile, tiers))

        sections = _build_sections(spans)
        if sections:
            chapters.append(ChapterEntry(
                title=marker.title,
                page_start=marker.page,
                sections=sections,
            ))

    return chapters


def _extract_auto_chapters(doc: fitz.Document, profile: BookProfile,
                            native_pages: list[int],
                            tiers: list[float]) -> list[ChapterEntry]:
    """
    Auto mode: the largest heading tier becomes chapter breaks, all smaller
    tiers become sections within those chapters.
    """
    all_spans: list[tuple[int | None, str, int]] = []
    for pn in native_pages:
        all_spans.extend(_page_spans(doc[pn], profile, tiers))

    if not tiers:
        # No heading tiers found — return everything as one chapter
        sections = _build_sections(all_spans)
        return [ChapterEntry(title="(Auto)", page_start=0, sections=sections)]

    # Tier 0 = largest = chapter breaks; everything else = section heading
    chapters: list[list] = []  # [title, page_start, [(tier, text, pn), ...]]
    for tier, text, pn in all_spans:
        if tier == 0:
            chapters.append([text, pn, []])
        else:
            if not chapters:
                chapters.append(["(Introduction)", pn, []])
            chapters[-1][2].append((tier, text, pn))

    result = []
    for title, page_start, ch_spans in chapters:
        sections = _build_sections(ch_spans)
        if sections:
            result.append(ChapterEntry(title=title, page_start=page_start,
                                       sections=sections))
    return result


def native_page_texts(doc: fitz.Document, profile: BookProfile,
                      native_pages: list[int], tiers: list[float]) -> list[NativePage]:
    """Return native page-level text for pages extracted by the chapter pipeline."""
    page_texts: dict[int, list[str]] = {pn: [] for pn in native_pages}
    for pn in native_pages:
        for _, text, _ in _page_spans(doc[pn], profile, tiers):
            page_texts[pn].append(text)

    return [NativePage(page_num=pn, text=" ".join(texts).strip())
            for pn, texts in sorted(page_texts.items())]


# ── step ──────────────────────────────────────────────────────────────────────

@step("extract_chapters")
def extract_chapters(pdf_path: Path, decisions: list[PageDecision],
                     profile: BookProfile) -> ChapterBook:
    native_pages = sorted(
        d.page_num for d in decisions if d.strategy == PageStrategy.NATIVE_TEXT
    )

    with fitz.open(pdf_path) as doc:
        tiers = _detect_font_tiers(doc, native_pages)
        body, heading_tiers = tiers
        import logging
        logging.getLogger(__name__).info(
            "font tiers — body=%.1fpt headings=%s",
            body, [f"{t:.1f}pt" for t in heading_tiers],
        )

        if profile.chapters:
            chapters = _extract_with_manual_chapters(
                doc, profile, native_pages, heading_tiers)
        else:
            chapters = _extract_auto_chapters(
                doc, profile, native_pages, heading_tiers)

    return ChapterBook(profile_name=profile.name, chapters=chapters)
