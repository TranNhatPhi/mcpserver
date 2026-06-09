"""PDF reading tool (text extraction via pypdf), sandboxed to the KB root."""

import os

from pypdf import PdfReader

from tools.file_tools import _display, _resolve

MAX_PDF_CHARS = 50_000


def read_pdf(path: str, max_pages: int = 30) -> str:
    """Extract text from a PDF file (path relative to the knowledge-base root).

    Returns the document text page by page, up to max_pages. Scanned PDFs with
    no embedded text will yield little or nothing (no OCR is performed).
    """
    abs_path = _resolve(path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Not a file: {_display(abs_path)}")
    if not abs_path.lower().endswith(".pdf"):
        raise ValueError(f"Not a PDF: {_display(abs_path)}")

    reader = PdfReader(abs_path)
    total = len(reader.pages)
    out = [f"PDF: {_display(abs_path)} ({total} page(s), showing up to {max_pages})"]
    chars = 0
    for i, page in enumerate(reader.pages[:max_pages], start=1):
        text = (page.extract_text() or "").strip()
        out.append(f"\n--- page {i} ---\n{text}")
        chars += len(text)
        if chars >= MAX_PDF_CHARS:
            out.append(f"\n...[truncated at {MAX_PDF_CHARS} characters]")
            break
    return "\n".join(out)
