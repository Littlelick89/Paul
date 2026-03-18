"""Convert PDF pages to PIL Images for OCR processing."""

from __future__ import annotations

import io
import base64
from pathlib import Path
from typing import Generator

from PIL import Image

import config


def pdf_to_images(pdf_path: str | Path) -> Generator[Image.Image, None, None]:
    """Yield one PIL Image per page of *pdf_path* at the configured DPI.

    Requires poppler to be installed on the system (pdf2image dependency).
    """
    from pdf2image import convert_from_path  # imported here so the rest of the
                                              # app still loads without poppler

    pages = convert_from_path(str(pdf_path), dpi=config.PDF_DPI)
    for page in pages:
        yield page


def image_to_base64(img: Image.Image, fmt: str = "PNG") -> str:
    """Return a base64-encoded string of *img* suitable for the Claude API."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.standard_b64encode(buf.getvalue()).decode()
