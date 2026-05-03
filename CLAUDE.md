# CLAUDE.md — TTRPG OCR Project

## Project Goal

Build a Python pipeline that takes a scanned TTRPG rulebook or adventure module (PDF) and outputs clean, structured text suitable for downstream analysis (search, embedding, LLM Q&A, etc.). Primary target source material: Warhammer Fantasy Roleplay supplements and similar books featuring:

- Heavy decorative page frames and ornaments
- Two- or three-column body layouts
- Inline illustrations, plates, and stat blocks
- Sidebars and call-out boxes with different fonts/sizes
- Ornate display fonts and varying scan quality (skew, bleedthrough, JPEG artifacts)

## Why This Is Hard (Read Before Suggesting Anything)

- Decorative page borders create false text regions and framing artifacts when OCR'd as text
- Multi-column reading order matters; naive top-to-bottom scanning destroys it
- Sidebars and stat blocks must be separated from main body text or they corrupt the narrative flow
- Inline images must be located so OCR doesn't garble them as text
- Old-style display fonts trip up Tesseract defaults
- Scan quality varies within a single book

The naive `pdf2image + pytesseract.image_to_string(page)` pipeline that most blog tutorials describe **does not work** on this material. Region-based processing is the project's whole point.

## Tech Stack

- Python 3.11+
- `pymupdf` (fitz) — PDF inspection and page rasterization
- `opencv-python` — preprocessing (deskew, denoise, binarize, contour ops)
- `pytesseract` — primary OCR engine, with explicit PSM/OEM tuning per region type
- `layoutparser` — layout analysis (start with classical CV, swap in pretrained model later)
- `pandas` — tabular intermediate results (region tables, OCR confidence tables)
- `pydantic` — schemas for inter-stage data
- `jiwer` — CER/WER evaluation
- `pytest` — testing
- Optional / for comparison only: `doctr`, `paddleocr`, `surya`

**Do not** introduce `unstructured.io` as the main backbone. It hides the components we are explicitly trying to learn.

**Ask before adding any dependency** not listed above.

## Project Structure

```
ttrpg-ocr/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── src/ttrpg_ocr/
│   ├── __init__.py
│   ├── ingest.py        # PDF type detection, page rasterization
│   ├── preprocess.py    # OpenCV preprocessing (deskew, denoise, binarize)
│   ├── layout.py        # frame/column/image region detection
│   ├── ocr.py           # OCR engine wrapper, per-region OCR
│   ├── postprocess.py   # dehyphenation, error correction, reading order
│   ├── schemas.py       # pydantic models (Page, Region, OcrResult)
│   └── pipeline.py      # orchestrator + CLI entrypoint
├── notebooks/           # exploration only — NEVER pipeline code
├── tests/
│   ├── data/            # ground-truth transcriptions for eval
│   └── ...
└── data/
    ├── raw/             # input PDFs (gitignored)
    └── processed/       # output JSON/markdown (gitignored)
```

## Coding Standards

- Type hints everywhere. Use `pathlib.Path`, not raw strings, for filesystem paths.
- Modules expose small pure functions where possible. I/O side effects live in `pipeline.py` or CLI entrypoints.
- Use `pydantic` models for anything passed between pipeline stages. No untyped dicts crossing module boundaries.
- Logging via `logging`, not `print`. INFO default, DEBUG for traces.
- No notebook code in `src/`. Notebooks are scratch space; promote to module only when the function is stable.
- Prefer pandas DataFrames for tabular intermediates (region tables, word-level OCR results) so they're inspectable.

## Style Preferences

- Direct and concise. No defensive over-engineering before there's a problem.
- Iterative: dumbest end-to-end version first, then improve the weakest stage. Don't perfect Phase 2 while Phase 5 doesn't exist.
- When proposing code, show the minimal version first; offer enhancements as an explicit second variant if relevant.
- Comments explain *why*, not *what*. The code should make *what* obvious.
- When suggesting a library API, show 3–8 lines of real usage, not a full wrapper class.

## Pipeline Contract

For each page, the pipeline produces:

1. A `Page` object: page number, raw image path, processed image path, list of `Region`s.
2. Each `Region`: bounding box, type (`text_body` | `text_sidebar` | `text_caption` | `image` | `frame_ornament`), reading order index, OCR text (if applicable), per-word confidence list.
3. A reconstructed page-level text in correct reading order, with sidebars marked (e.g. fenced as `> [SIDEBAR] ...`).

Final book-level output: one JSON file conforming to schema, optionally rendered to markdown.

## Profiles

The pipeline supports multiple book layout families via profiles. A profile
is a YAML file in `profiles/` that captures book-family-specific config:
DPI, frame detection strategy, column count, PSM choices, proper noun
dictionaries, etc.

- New book of an existing family → new profile, no code changes.
- New book exposing a capability gap → add the capability as an opt-in
  module, then profiles enable it via config.
- Never hardcode book-specific values in `src/`. If you find yourself
  wanting to, add it to the profile schema instead.
- The profile schema lives in `src/ttrpg_ocr/schemas.py` as `BookProfile`.
- `tests/data/` contains ground-truth pages per profile. Eval reports CER
  per profile, not globally.

## Common OCR Pitfalls — Anticipate These

- Don't OCR the whole page in one shot for multi-column books. Always crop to text regions first.
- Tesseract default PSM is 3 (auto). For uniform body columns use `--psm 6`. For sidebars try `--psm 4`. For sparse text `--psm 11`.
- Rasterize at 300 DPI minimum, 400 DPI for fine print. Watch RAM at 400+.
- Deskew **before** binarization. Otherwise the skew is baked into a thresholded image.
- Don't dehyphenate blindly. `co-operate` should stay; `co-\noperate` should join. Dictionary check both forms before merging.
- Bleedthrough from the next page produces phantom characters. Aggressive denoise helps but can erase thin strokes — tune carefully.
- TTRPG proper nouns (`Marienburg`, `Khazalid`, `Sigmar`) will fail spell-check. Don't autocorrect against a generic dictionary.

## Validation

- `tests/data/` contains 2–3 manually transcribed pages as ground truth (one body-heavy, one sidebar-heavy, one with images).
- `jiwer` computes CER and WER per page and per region.
- Any pipeline change must not regress CER on the test pages beyond a documented threshold (start at +0.5%).
- Eval runs as a pytest test, not a separate script.

## What I Want From You (Claude Code)

- **Ask before adding dependencies.** This is a learning project; gratuitous library use defeats the purpose.
- **When I'm stuck, propose 2–3 approaches with tradeoffs before writing code.** Don't pick for me.
- **Push back if I ask for something that contradicts this file.** Cite the section.
- **For unfamiliar libraries (`layoutparser`, `paddleocr`), show 3–8 lines of real API usage** with a one-sentence explanation of what each line does, before integrating them.
- **Tests use real fixture pages, not mocks.** The point of the project is that real-world data is messy.
- **Don't write the full module in one shot.** Scaffold the function signature with a docstring and one happy-path implementation, let me read it, then iterate.
- **Notebook explorations stay in notebooks** until the function is stable. Don't preemptively extract.

## Out of Scope (For Now)

- Table extraction beyond stat blocks (no CSV-export of tables).
- Translation or language detection. Output stays in source language.
- Visual layout reconstruction. We extract content; we don't preserve formatting.
- Vector PDFs with native text — different problem. Detect this case in `ingest.py` and route to a separate path that uses `pymupdf.get_text()` directly.
- Web UI, API server, or any deployment concerns.
- Auto-detection of which profile to use. Manual selection via CLI flag (--profile wfrp_2e) until we have 5+ profiles.

## Useful References

- Tesseract PSM/OEM docs: https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
- LayoutParser: https://layout-parser.github.io/
- PyImageSearch document preprocessing posts (deskew, threshold)
- `jiwer` for evaluation: https://github.com/jitsi/jiwer
