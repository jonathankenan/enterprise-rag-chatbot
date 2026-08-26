"""
Regression tests for _extract_pages_with_fallback() page attribution.

Run from the repo root:   python backend/tests/test_pdf_page_extraction.py
(or with pytest:          pytest backend/tests/test_pdf_page_extraction.py)

Needs only pymupdf + pymupdf4llm (already in requirements.txt). Builds its own
PDFs in memory, so there is no fixture file to keep in sync.

Covers the 2026-08-25 fix. The old implementation split whole-document
markdown on '\\n\\n-----\\n\\n' and guarded with len(segments) == len(doc),
which failed in both directions:

  * ordinary PDF -> trailing separator made len() = page_count + 1, guard
    failed, ALL page numbers discarded (page=None everywhere)
  * PDF with a blank/image-only first page -> leading empty segment cancelled
    the trailing one, len() MATCHED, guard passed, every segment off by one

Both are asserted below so neither can come back.
"""
import ast
import io
import re
import sys
from pathlib import Path

import pymupdf as fitz
import pymupdf4llm

APP = Path(__file__).resolve().parents[1] / "app"
if not APP.is_dir():
    raise SystemExit(f"cannot find backend/app at {APP}")


def _load():
    src = (APP / "rag" / "vectorstore.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)
                and n.name == "_extract_pages_with_fallback")
    ns = {"re": re, "fitz": fitz, "pymupdf4llm": pymupdf4llm}
    exec(ast.get_source_segment(src, node), ns)
    return ns["_extract_pages_with_fallback"]


extract = _load()


def _build(blank_first_page: bool, n_pages: int = 5) -> fitz.Document:
    """Page k carries the unique marker 'SECTION k'. Optionally page 1 is
    image-only, mimicking a scanned cover sheet (the NEXUS BRD case)."""
    doc = fitz.open()
    p = doc.new_page()
    if blank_first_page:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 120))
        pix.clear_with(200)
        p.insert_image(fitz.Rect(100, 100, 300, 220), pixmap=pix)
    else:
        p.insert_text((72, 100), "SECTION 1 HEADING", fontsize=14)
        p.insert_text((72, 130), "Body prose of section 1.", fontsize=11)
    for k in range(2, n_pages + 1):
        p = doc.new_page()
        p.insert_text((72, 100), f"SECTION {k} HEADING", fontsize=14)
        p.insert_text((72, 130), f"Body prose of section {k}.", fontsize=11)
    return fitz.open("pdf", doc.tobytes())


def _markdown_section(text: str) -> str | None:
    """Which SECTION the markdown half of an entry claims (ignore fallback)."""
    md = text.split("<!-- plain-text fallback")[0]
    m = re.search(r"SECTION (\d+)", md)
    return m.group(1) if m else None


def _assert_aligned(doc, pages):
    """Every entry's page number must match the SECTION marker fitz reads
    off that very page, and the markdown half must not belong to another."""
    truth = {}
    for i, page in enumerate(doc):
        m = re.search(r"SECTION (\d+)", page.get_text())
        truth[i + 1] = m.group(1) if m else None

    assert len(pages) == len(truth), f"expected {len(truth)} entries, got {len(pages)}"
    for entry in pages:
        pno = entry["page"]
        assert pno is not None, "page number was discarded"
        claimed = _markdown_section(entry["text"])
        if claimed is not None:
            assert claimed == truth[pno], (
                f"page {pno} markdown claims SECTION {claimed}, "
                f"but that page really holds SECTION {truth[pno]}")
        # the page's own text must be present somewhere in the entry
        if truth[pno] is not None:
            assert f"SECTION {truth[pno]}" in entry["text"], (
                f"page {pno} entry is missing its own content")


def test_ordinary_pdf_keeps_page_numbers():
    """Old bug: trailing '-----' made the guard fail and blanked every page."""
    doc = _build(blank_first_page=False)
    pages = extract(doc)
    assert all(p["page"] is not None for p in pages), \
        "regression: page numbers discarded for an ordinary PDF"
    _assert_aligned(doc, pages)
    doc.close()


def test_blank_first_page_does_not_shift_alignment():
    """Old bug: empty leading segment cancelled the trailing one, guard
    passed, and every page's markdown came from the page after it."""
    doc = _build(blank_first_page=True)
    pages = extract(doc)
    _assert_aligned(doc, pages)
    doc.close()


def test_pages_are_one_indexed_and_in_order():
    doc = _build(blank_first_page=False, n_pages=4)
    pages = extract(doc)
    assert [p["page"] for p in pages] == [1, 2, 3, 4]
    doc.close()


def test_blank_page_still_gets_an_entry():
    """A page with nothing extractable must still occupy its slot, or every
    later page shifts down -- the whole cause of the original bug."""
    doc = _build(blank_first_page=True, n_pages=3)
    pages = extract(doc)
    assert len(pages) == 3
    assert pages[0]["page"] == 1
    doc.close()


def test_plain_text_fallback_still_fires_and_carries_content():
    """The safety net for pymupdf4llm dropping post-table prose must survive
    the rewrite -- and must now cite the page it actually came from."""
    doc = _build(blank_first_page=False)
    pages = extract(doc)
    for entry in pages:
        for m in re.finditer(r"plain-text fallback page (\d+)", entry["text"]):
            assert int(m.group(1)) == entry["page"], \
                "fallback marker names a different page than its entry"
    doc.close()


if __name__ == "__main__":
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
