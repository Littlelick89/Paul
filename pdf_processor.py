"""Convert PDF pages to PIL Images for OCR processing."""

from __future__ import annotations

import io
import base64
import os
import shutil
from pathlib import Path
from typing import Generator

from PIL import Image

import config


# Directories to search for poppler on Windows (in priority order).
# Add or change these if your poppler is installed elsewhere.
_POPPLER_SEARCH_DIRS: list[Path] = [
    Path(__file__).parent / "poppler-25.12.0" / "bin",   # next to main.py
    Path(__file__).parent / "poppler" / "bin",
    Path(r"C:\Program Files\poppler\bin"),
    Path(r"C:\tools\poppler\bin"),
]


def _find_poppler() -> str | None:
    """Return the poppler/bin path if found locally; None = rely on system PATH."""
    for candidate in _POPPLER_SEARCH_DIRS:
        if (candidate / "pdftoppm.exe").exists() or (candidate / "pdftoppm").exists():
            return str(candidate)
    # Also accept it already being on PATH
    if shutil.which("pdftoppm"):
        return None          # None tells pdf2image to use PATH
    return None              # Will raise a clear error from pdf2image


def pdf_to_images(pdf_path: str | Path) -> Generator[Image.Image, None, None]:
    """Yield one PIL Image per page of *pdf_path* at the configured DPI.

    Poppler is located automatically:
      1. Checked in common local directories (see _POPPLER_SEARCH_DIRS).
      2. Falls back to the system PATH.
    """
    from pdf2image import convert_from_path  # late import: app loads without poppler

    poppler_path = _find_poppler()
    pages = convert_from_path(str(pdf_path), dpi=config.PDF_DPI, poppler_path=poppler_path)
    for page in pages:
        yield page


def image_to_base64(img: Image.Image, fmt: str = "PNG") -> str:
    """Return a base64-encoded string of *img* suitable for the Claude API."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.standard_b64encode(buf.getvalue()).decode()
