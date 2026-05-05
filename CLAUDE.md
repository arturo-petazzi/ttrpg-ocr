# CLAUDE.md — ttrpg-ocr

## Project Goal

Extract clean, reading-order-correct text from TTRPG rulebooks and adventure
modules (PDF) for downstream use: search, embedding, LLM Q&A, corpus analysis.
Primary targets are Warhammer Fantasy Roleplay supplements; secondary targets
include any TTRPG book with structured text layout.

**We only want text.** Full-page illustrations, maps, indexes, and front/back
matter are explicitly excluded. Image regions within text pages are marked as
`[IMAGE]` placeholders, not extracted.

---

## What We Learned About TTRPG PDFs (Read Before Assuming Anything)

Most books are **hybrid PDFs**, not pure scans. Inspection of Marienburg: Sold
Down the River revealed:

- 152/168 pages have native embedded text (`get_text()` returns 800–7500 chars)
- 16 pages are skipped: 15 manual drops (cover, ToC, index, full-page art) + 1
  genuine image-only page
- Every page has a header image (1100+ × 110px banner strip at the top)
- Pages with side illustrations shift the two text columns rightward — a fixed
  page-midpoint column split fails on these pages
- Some pages use 1, 2, or 3 columns depending on layout (chapter openers,
  sidebars, stat blocks)
- Small decorative images (borders, rules, drop caps) appear alongside real
  illustrations — filter by area, not just by image type
- Page dimensions vary slightly page-to-page (~590–605 × 784–790 pts) — don't
  hardcode pixel values

**Column detection must be per-page and gap-based**, not a fixed midpoint split.
The page profile specifies a maximum column count; actual count is detected from
the distribution of text block x-centers on each page.

---

## Architecture: Two-Path Pipeline

```
@pipeline process_book
  ├── @step classify_pages       → list[PageDecision]
  ├── @step extract_native       → list[Page]   (pymupdf native text)
  ├── @step extract_ocr          → list[Page]   (Tesseract; stub until needed)
  └── @step assemble_book        → Book
```

**Page routing:**
- `NATIVE_TEXT` — embedded text chars >= `native_text_min_chars` → native path
- `SKIP` — in `drop_pages` list, or no text and OCR disabled → discard
- `SCAN_OCR` — no native text and `enable_ocr: true` in profile → OCR path

The OCR path is a `NotImplementedError` stub until we have a book that needs it.
Build native path end-to-end first, validate, then come back to OCR.

The `@pipeline` and `@step` decorators (in `pipeline_utils.py`) handle run-id
propagation via `contextvars`, timing, structured logging, and a nested-step
guard. **Never nest `@step` inside another `@step`.** Per-page functions are
plain helpers (leading underscore, no decorator).

---

## Project Structure

```
ttrpg-ocr/                        <- repo root (hyphen ok here)
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── profiles/
│   └── book1.yaml                <- one file per book/family
├── src/
│   └── ttrpg_ocr/                <- import name (underscore); MUST match pyproject name
│       ├── __init__.py           <- empty; required
│       ├── schemas.py            <- pydantic models: BookProfile, Page, Region, Book
│       ├── profiles.py           <- load_profile(path) -> BookProfile
│       ├── classify.py           <- classify_pages step + PageDecision, PageStrategy
│       ├── extract_text.py     <- extract_native step + private helpers
│       ├── extract_ocr.py        <- stub; raises NotImplementedError
│       ├── assemble.py           <- assemble_book step
│       └── pipeline.py           <- process_book orchestrator + main() CLI
├── notebooks/                    <- exploration only; never import from src here
│                                    without installing the package (uv run jupyter lab)
├── tests/
│   ├── data/                     <- ground-truth transcriptions per profile
│   └── test_extract_native.py    <- unit tests for column detection helpers
└── data/
    ├── raw/                      <- input PDFs (gitignored)
    └── processed/                <- output JSON + markdown (gitignored)
```

**src layout is intentional.** The extra `src/` level forces the package to be
installed before it can be imported. This means `uv sync` / `pip install -e .`
behavior matches prod. Without it, `import ttrpg_ocr` works from the repo root
by accident and you cannot catch packaging bugs. Do not move files out of
`src/ttrpg_ocr/`.

---

## pyproject.toml — Correct Form

```toml
[project]
name = "ttrpg-ocr"
version = "0.1.0"
description = "OCR pipeline for extracting structured text from scanned TTRPG rulebooks"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "common",
    "jiwer>=4.0.0",
    "numpy>=2.4.4",
    "opencv-python>=4.13.0.92",
    "pandas>=3.0.2",
    "pillow>=12.2.0",
    "pydantic>=2.13.3",
    "pymupdf>=1.27.2.3",
    "pytesseract>=0.3.13",
    "pyyaml>=6.0.3",
    "tqdm>=4.67.3",
]

[tool.uv.sources]
common = { path = "../common", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ttrpg_ocr"]

[project.scripts]
ttrpg-ocr = "ttrpg_ocr.pipeline:main"
```

**`[tool.hatch.build.targets.wheel]` is required.** Without it hatchling cannot
find the package and `uv add <anything>` fails with:
`ValueError: Unable to determine which files to ship inside the wheel`.

**`build-backend` must be `"hatchling.build"`**, not `"hatchling"` — the module
path requires the `.build` suffix.

**`readme` must be a plain string `"README.md"`**, not a markdown link. See the
auto-linkifier bug below.

---

## Known Tooling Issues

### Auto-linkifier corrupts config files

Something on the dev machine (likely a clipboard manager or browser extension)
wraps strings that look like domain names in markdown link syntax:

- `README.md` becomes `[README.md](http://README.md)`
- `hatchling.build` becomes `[hatchling.build](http://hatchling.build)`
- `tool.hatch.build` becomes `[tool.hatch.build](http://tool.hatch.build)`

This silently breaks `pyproject.toml`. The `[tool.hatch.build.targets.wheel]`
section header becomes invalid TOML; hatchling ignores the block and falls back
to broken auto-discovery. **Always run `grep -n "http://" pyproject.toml` before
`uv sync`.** Track down and disable the source (Raycast, Alfred, browser
extension).

### `uv add <package>` fails even for unrelated packages

Symptom: `uv add pandas` fails with a hatchling error about not finding the
package. Cause: `uv add` syncs the venv after resolving, which requires building
your project editable. If hatchling can't find the package the sync fails and
the new dep is never installed — even though it was written to `pyproject.toml`.

Fix order:
1. Fix `pyproject.toml` (check for corrupt TOML, verify `[tool.hatch.build.targets.wheel]`)
2. `uv pip uninstall ttrpg-ocr`
3. `rm -rf .venv uv.lock`
4. `uv sync`

### Stale editable install after rename or restructure

After renaming the repo folder or moving source files, `uv sync` may report
"already installed" but `import ttrpg_ocr` fails because the install points at
the old path. Symptom: `uv pip list | grep ttrpg` shows the package with the
old path.

Fix: `rm -rf .venv uv.lock && uv sync`. Always do this after any rename or
restructure.

### Notebook kernel mismatch

Symptom: `import ttrpg_ocr` works in terminal (`uv run python -c ...`) but
fails in notebook with `ModuleNotFoundError`.

Cause: notebook kernel is a different Python interpreter (system Python, conda
env) that doesn't have the package installed.

Diagnosis: in a notebook cell run `import sys; print(sys.executable)`. If it
does not end in `.venv/bin/python` the kernel is wrong.

Fix in VS Code: click kernel selector top-right → Python Environments → pick
`.venv (Python 3.12.x) ./.venv/bin/python`. If `.venv` is not listed, install
ipykernel first: `uv add --dev ipykernel && uv sync`, then reload VS Code
(Cmd+Shift+P → "Developer: Reload Window").

Fix in terminal Jupyter: always launch with `uv run jupyter lab`, never plain
`jupyter lab`.

Make it permanent — add to `.vscode/settings.json`:
```json
{ "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python" }
```

Never use `sys.path.insert` as a workaround. Fix the kernel.

Add to the top of every notebook:
```python
%load_ext autoreload
%autoreload 2
```
This picks up edits to `src/` without restarting the kernel.

---

## Profiles: YAML Values + Pydantic Schema

A profile is a YAML file in `profiles/` validated by the `BookProfile` pydantic
model. YAML holds the per-book values; pydantic defines and validates the schema.

```python
# src/ttrpg_ocr/profiles.py
def load_profile(path: Path) -> BookProfile:
    return BookProfile(**yaml.safe_load(path.open()))
```

`BookProfile` uses `model_config = ConfigDict(extra="forbid")` so typos in YAML
raise `ValidationError` at load time instead of silently using wrong defaults.

New book of an existing family: write a new YAML, no code changes.
New capability needed: add an opt-in field with a safe default to `BookProfile`,
then enable it in the specific profile YAML. Never hardcode book-specific values
in `src/`.

### Current BookProfile fields

```python
class BookProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    # Rasterization (OCR path only)
    dpi: int = Field(default=300, ge=72, le=600)
    # Page routing
    enable_ocr: bool = False
    native_text_min_chars: int = Field(default=500, ge=0)
    drop_pages: list[int] = Field(default_factory=list)
    # Layout
    has_header: bool = True
    header_height_pct: float = Field(default=0.08, ge=0.0, le=0.5)
    footer_height_pct: float = Field(default=0.05, ge=0.0, le=0.5)
    column_count_max: int = Field(default=2, ge=1, le=4)
    column_gap_min_pct: float = Field(default=0.08, ge=0.01, le=0.3)
    # Images
    mark_images_in_output: bool = True
    min_image_area_px: int = Field(default=5000, ge=0)
    # OCR (only relevant when enable_ocr: true)
    body_psm: int = Field(default=6, ge=0, le=13)
    sidebar_psm: int = Field(default=4, ge=0, le=13)
    caption_psm: int = Field(default=7, ge=0, le=13)
    tesseract_lang: str = "eng"
```

### book1.yaml (Marienburg: Sold Down the River)

```yaml
name: book1
enable_ocr: false
native_text_min_chars: 500
drop_pages: [0, 1, 2, 3, 4, 165, 166, 167]  # covers, ToC, index, back matter
has_header: true
header_height_pct: 0.08
footer_height_pct: 0.05
column_count_max: 3
column_gap_min_pct: 0.08
mark_images_in_output: true
min_image_area_px: 5000
dpi: 150
```

`dpi: 150` because source scans are ~150 DPI (1260x1635px on an 8.4x10.9in
page). Setting higher would upscale without adding information.

---

## Column Detection: How and Why

**Problem.** A fixed page-midpoint split fails on pages where a side illustration
pushes both text columns into the right portion of the page. Page 14 of book1
demonstrated this: left-column body had x_center=299 on a 594pt page, and was
misclassified as column 1.

**Solution.** Per-page gap-based detection:
1. Collect x-centers of all candidate text blocks on the page.
2. Sort and compute consecutive gaps between them.
3. Count gaps wider than `column_gap_min_pct * page_width`; n_cols = count + 1,
   capped at `column_count_max`.
4. Assign columns by splitting at the midpoints of those large gaps.

This makes no assumption about column widths or absolute positions.

**Edge cases handled:**
- Fewer than 4 text blocks → return 1 (not enough data to detect gaps reliably)
- Detected count exceeds `column_count_max` → cap it
- Empty page after header/footer strip → return empty Page, do not crash

**Key private functions in `extract_native.py`:**
- `_detect_column_count(x_centers, page_width, max_cols, gap_min_pct) -> int`
- `_assign_columns(x_centers, n_cols) -> list[int]`
- `_extract_native_one(page, profile) -> Page`

These are pure functions (no I/O). Unit-test them with synthetic float lists;
no PDF fixture required.

---

## Schemas

```python
class RegionType(str, Enum):
    HEADER = "header"
    TEXT_BODY = "text_body"
    TEXT_SIDEBAR = "text_sidebar"
    TEXT_CAPTION = "text_caption"
    IMAGE = "image"
    FRAME_ORNAMENT = "frame_ornament"

class BBox(BaseModel):
    x: int; y: int; w: int; h: int

class OcrWord(BaseModel):
    text: str; conf: float; bbox: BBox

class Region(BaseModel):
    type: RegionType
    bbox: BBox
    reading_order: int
    text: str = ""
    words: list[OcrWord] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)  # stage-internal scratch (e.g. column index)

class Page(BaseModel):
    page_num: int
    image_path: Path          # empty Path() for native-text pages
    regions: list[Region] = Field(default_factory=list)
    reconstructed_text: str = ""

class PageDecision(BaseModel):
    page_num: int
    strategy: PageStrategy    # NATIVE_TEXT | SCAN_OCR | SKIP
    reason: str
    text_chars: int
    image_count: int

class Book(BaseModel):
    profile_name: str
    pages: list[Page]
    decisions: list[PageDecision]
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

`Region.extra` is a sanctioned escape hatch for data internal to a pipeline
stage (e.g. `{"column": 1}`). Promote to a proper field if it crosses a module
boundary.

---

## Coding Standards

- `from __future__ import annotations` at the top of every module.
- Type hints on all function signatures. `pathlib.Path` for all file paths.
- Pure functions for all logic. I/O lives only in `pipeline.py` and CLI.
- Internal helpers: leading underscore, no `@step` decorator. The nested-step
  guard raises `RuntimeError` if a `@step` calls another `@step`.
- `logging` not `print`. INFO for pipeline/step boundaries; DEBUG for per-page
  detail.
- No notebook code in `src/`. Notebooks explore; `src/` ships.
- Relative imports within the package: `from .schemas import Page`.

---

## Style Preferences

- Minimal and direct. No defensive abstractions before a second case exists.
- Show the working version first; enhancements are an explicit second variant.
- Comments explain *why*, not *what*.
- Iterate on real output. Run it, read it, find what's wrong. Don't tune against
  assumptions.

---

## Testing

Two layers, both required.

**Unit tests (`pytest`, fast, no PDF).** Test pure helper functions with
synthetic input. File: `tests/test_extract_native.py`. Current cases cover:
two-column normal page, three-column page, single-column (no significant gap),
too-few-blocks fallback, `max_cols` cap, left-shifted two-column page (the
page-14 regression), column assignment preserving input order.

Run with: `uv run pytest tests/test_extract_native.py -v`

**Integration checks (notebook, eyeballed).** Run `_extract_native_one` on
validation pages and read the output. Validation set for book1: pages 7
(normal 2-col), 14 (left-shifted 2-col), 38 (3 sections + sidebar), 69
(illustrations), 80 (mixed), 100 (NPC stat blocks), 150 (name lists).

For each page verify: (1) detected column count matches PDF, (2) left column
fully done before right column starts, (3) no header/footer bleed, (4) image
markers in plausible positions.

**CER/WER evaluation.** Ground-truth transcriptions in `tests/data/book1/page_NNN.txt`.
Target CER < 10% on native-text pages (expect near-zero; no OCR error source).
Eval runs as a pytest test. Regressions > 0.5% CER block merge.

---

## What I Want From You (Claude Code)

- **Ask before adding dependencies.** This is a learning project.
- **Propose 2-3 approaches with tradeoffs** when the path is unclear. Don't
  pick for me.
- **Push back if I ask for something that contradicts this file.** Cite the
  section.
- **Internal helpers are not steps.** Never add `@step` to a leading-underscore
  function or any per-page function.
- **Tests use real fixture pages or synthetic float lists**, not mocks of pymupdf
  internals.
- **Don't write a full module in one shot.** Scaffold → I read → iterate.
- **Notebook explorations stay in notebooks** until the function is stable.
- **Check for the auto-linkifier bug** before finalising any config file:
  `grep -n "http://" pyproject.toml` must return nothing.

---

## Out of Scope (For Now)

- OCR path implementation (stub exists; implement when first fully-scanned book
  is in scope).
- Table extraction beyond stat blocks.
- Translation or language detection.
- Visual layout reconstruction (content only, not formatting).
- Auto-detection of which profile to apply (manual `--profile` flag until 5+
  profiles exist).
- Web UI, API, or any deployment concerns.
- `unstructured.io` as the main backbone.

---

## Reference

- pymupdf `get_text` modes: https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_text
- Tesseract PSM/OEM: https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
- pydantic v2 model config: https://docs.pydantic.dev/latest/concepts/config/
- jiwer CER/WER: https://github.com/jitsi/jiwer
- Conventional commits: https://www.conventionalcommits.org/