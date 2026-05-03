from __future__ import annotations
from pathlib import Path
import fitz
from .schemas import BookProfile, Page, Region, RegionType, BBox
from .classify import PageDecision, PageStrategy
from common.pipeline import step


def _detect_column_count(x_centers: list[float], page_width: float,
                          max_cols: int, gap_min_pct: float) -> int:
    """Detect the number of text columns from block x-centers.

    Counts gaps between consecutive (sorted) x-centers that are wider than
    `gap_min_pct` of page width. n columns = n-1 such gaps + 1, capped at max_cols.
    Returns 1 when there's too little text to decide.
    """
    if len(x_centers) < 4:
        return 1
    sorted_xs = sorted(x_centers)
    gaps = [sorted_xs[i + 1] - sorted_xs[i] for i in range(len(sorted_xs) - 1)]
    min_gap = page_width * gap_min_pct
    significant = [g for g in gaps if g > min_gap]
    return min(len(significant) + 1, max_cols)


def _assign_columns(x_centers: list[float], n_cols: int) -> list[int]:
    """Assign each x-center to a column index in [0, n_cols).

    Splits at the n_cols-1 largest gaps in the sorted x-centers. Returns
    column indices in the original order of x_centers.
    """
    if n_cols <= 1 or len(x_centers) < n_cols:
        return [0] * len(x_centers)

    indexed = sorted(enumerate(x_centers), key=lambda p: p[1])
    sorted_xs = [x for _, x in indexed]
    original_indices = [i for i, _ in indexed]

    gaps = sorted(
        ((sorted_xs[i + 1] - sorted_xs[i], i) for i in range(len(sorted_xs) - 1)),
        reverse=True,
    )
    boundary_idx_in_sorted = sorted(g[1] for g in gaps[: n_cols - 1])
    boundaries = [
        (sorted_xs[i] + sorted_xs[i + 1]) / 2 for i in boundary_idx_in_sorted
    ]

    def to_col(x: float) -> int:
        for i, b in enumerate(boundaries):
            if x < b:
                return i
        return len(boundaries)

    cols = [0] * len(x_centers)
    for orig_idx, x in zip(original_indices, sorted_xs):
        cols[orig_idx] = to_col(x)
    return cols


def _extract_native_one(page: fitz.Page, profile: BookProfile) -> Page:
    """Extract one page's text via pymupdf, sort into reading order."""
    page_w = page.rect.width
    page_h = page.rect.height
    header_cutoff_y = page_h * profile.header_height_pct
    footer_cutoff_y = page_h * (1 - profile.footer_height_pct)

    # 1. Collect candidate text blocks, dropping header/footer/empty.
    candidates: list[tuple[float, float, float, float, str]] = []
    for x0, y0, x1, y1, text, _, block_type in page.get_text("blocks"):
        if block_type != 0:  # 0 = text, 1 = image
            continue
        text = text.strip()
        if not text:
            continue
        if y0 < header_cutoff_y or y1 > footer_cutoff_y:
            continue
        candidates.append((x0, y0, x1, y1, text))

    if not candidates:
        return Page(
            page_num=page.number, image_path=Path(""),
            regions=[], reconstructed_text="",
        )

    # 2. Detect column count for THIS page, then assign each block to a column.
    x_centers = [(c[0] + c[2]) / 2 for c in candidates]
    n_cols = _detect_column_count(
        x_centers, page_w,
        max_cols=profile.column_count_max,
        gap_min_pct=profile.column_gap_min_pct,
    )
    columns = _assign_columns(x_centers, n_cols)

    # 3. Build text regions.
    regions: list[Region] = []
    for (x0, y0, x1, y1, text), col in zip(candidates, columns):
        regions.append(Region(
            type=RegionType.TEXT_BODY,
            bbox=BBox(x=int(x0), y=int(y0), w=int(x1 - x0), h=int(y1 - y0)),
            reading_order=0,
            text=text,
            extra={"column": col},
        ))

    # 4. Optionally add image markers, assigned to a column by their center.
    if profile.mark_images_in_output:
        for img_rect in page.get_image_rects(...) if False else []:
            pass  # see note below — image rects need a slightly different call
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 1:  # 1 = image block in dict mode
                continue
            x0, y0, x1, y1 = block["bbox"]
            if y0 < header_cutoff_y or y1 > footer_cutoff_y:
                continue
            if (x1 - x0) * (y1 - y0) < profile.min_image_area_px:
                continue
            col_centers_only = [(x0 + x1) / 2]
            # Use the same boundaries we already computed for text by passing
            # the image's x-center alongside; simpler: assign by midpoint among
            # detected text columns.
            img_col = _assign_columns(x_centers + [(x0 + x1) / 2], n_cols)[-1]
            regions.append(Region(
                type=RegionType.IMAGE,
                bbox=BBox(x=int(x0), y=int(y0), w=int(x1 - x0), h=int(y1 - y0)),
                reading_order=0,
                text="[IMAGE]",
                extra={"column": img_col},
            ))

    # 5. Sort by (column, y), assign reading order, reconstruct text.
    regions.sort(key=lambda r: (r.extra["column"], r.bbox.y))
    for i, r in enumerate(regions):
        r.reading_order = i

    reconstructed = "\n\n".join(r.text for r in regions)
    return Page(
        page_num=page.number, image_path=Path(""),
        regions=regions, reconstructed_text=reconstructed,
    )


@step("extract_text")
def extract_text(pdf_path: Path, decisions: list[PageDecision],
                    profile: BookProfile) -> list[Page]:
    """Extract all NATIVE_TEXT pages from the PDF."""
    targets = sorted({
        d.page_num for d in decisions
        if d.strategy == PageStrategy.NATIVE_TEXT
    })
    if not targets:
        return []
    pages: list[Page] = []
    with fitz.open(pdf_path) as doc:
        for n in targets:
            pages.append(_extract_native_one(doc[n], profile))
    return pages