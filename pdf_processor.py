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
    Path(__file__).parent / "bin",                        # ./bin  ← 현재 구조
    Path(__file__).parent / "poppler-25.12.0" / "bin",
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


_API_IMAGE_LIMIT = 4 * 1024 * 1024  # 4 MB (Anthropic hard limit is 5 MB)


def image_to_base64_with_type(img: Image.Image) -> tuple[str, str]:
    """Return (base64_data, media_type) for the Claude API.

    Tries PNG first; falls back to JPEG if the PNG exceeds *_API_IMAGE_LIMIT*.
    Returns the appropriate ``media_type`` string alongside the encoded data.
    """
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    if buf.tell() <= _API_IMAGE_LIMIT:
        return base64.standard_b64encode(buf.getvalue()).decode(), "image/png"

    for quality in (95, 85, 75):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        if buf.tell() <= _API_IMAGE_LIMIT:
            break

    return base64.standard_b64encode(buf.getvalue()).decode(), "image/jpeg"


def image_to_base64(img: Image.Image, fmt: str = "PNG") -> str:
    """Return a base64-encoded string of *img* suitable for the Claude API.

    Always tries PNG first (lossless, best quality).  If the PNG payload would
    exceed *_API_IMAGE_LIMIT* bytes, falls back to JPEG quality=95 and then
    quality=85 so the image stays within the Anthropic 5 MB per-image limit
    while preserving as much detail as possible.
    """
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    if buf.tell() <= _API_IMAGE_LIMIT:
        return base64.standard_b64encode(buf.getvalue()).decode()

    # PNG is too large — fall back to JPEG with decreasing quality.
    for quality in (95, 85, 75):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        if buf.tell() <= _API_IMAGE_LIMIT:
            break

    return base64.standard_b64encode(buf.getvalue()).decode()
