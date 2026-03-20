"""Local OCR extractor — CPU-only, no API key required.

Pipeline
--------
  PaddleOCR  → text fields  (name, date, course, comments …)
  OpenCV     → checkbox / Likert-table detection  (Q1-Q15, Q9_1-Q9_5, Q10-Q39)

Estimated accuracy at 400 DPI: ~73-78 % for this document type.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import cv2
import numpy as np
from PIL import Image

import config
from ocr_extractor import merge_records  # reuse existing merge logic


# ─────────────────────────────────────────────────────────────────────────────
# PaddleOCR  (lazy singleton — first call initialises the model)
# ─────────────────────────────────────────────────────────────────────────────

_paddle: Any = None
_paddle_lock = threading.Lock()


def _get_paddle():
    global _paddle
    if _paddle is not None:
        return _paddle
    with _paddle_lock:
        if _paddle is not None:          # re-check after acquiring lock
            return _paddle
        import logging
        import sys
        logging.disable(logging.WARNING)

        # If PyTorch DLLs are broken (WinError 127 on shm.dll), pre-import and
        # stub it out so paddle's optional-torch check does not crash.
        if "torch" not in sys.modules:
            try:
                import torch  # noqa: F401
            except (OSError, ImportError):
                from unittest.mock import MagicMock
                sys.modules["torch"] = MagicMock()

        # Disable PIR mode + OneDNN before paddle initialises (PaddlePaddle 3.x bug).
        try:
            import paddle
            paddle.set_flags({"FLAGS_enable_pir_api": False})
        except Exception:
            pass
        try:
            import paddle.core as _pc
            _pc.set_pir_enabled(False)
        except Exception:
            pass

        from paddleocr import PaddleOCR  # type: ignore

        # Candidate argument sets, from richest (2.x) to minimal (3.x).
        # Catch ALL exceptions so that "Unknown argument: X" style errors are
        # also handled, not just TypeError.
        _init_candidates = [
            {"use_angle_cls": True, "lang": "korean", "show_log": False, "enable_mkldnn": False},
            {"use_angle_cls": True, "lang": "korean", "show_log": False},
            {"use_angle_cls": True, "lang": "korean"},
            {"lang": "korean"},
        ]
        last_exc: Exception | None = None
        for kwargs in _init_candidates:
            try:
                _paddle = PaddleOCR(**kwargs)
                break
            except Exception as exc:
                last_exc = exc
        if _paddle is None:
            raise RuntimeError(f"PaddleOCR 초기화 실패: {last_exc}")

        logging.disable(logging.NOTSET)
    return _paddle


def _run_ocr(img: Image.Image) -> list[dict]:
    """Run PaddleOCR; return list of {text, conf, x1, y1, x2, y2}."""
    import logging
    arr = np.array(img.convert("RGB"))
    paddle = _get_paddle()

    # Try 2.x API first (ocr + cls), then 3.x API (ocr / predict).
    result = None
    logging.disable(logging.WARNING)
    for call in [
        lambda: paddle.ocr(arr, cls=True),
        lambda: paddle.ocr(arr),
        lambda: paddle.predict(arr),
    ]:
        try:
            result = call()
            break
        except Exception:
            continue
    logging.disable(logging.NOTSET)

    items: list[dict] = []
    if result is None or len(result) == 0:
        return items

    # PaddleOCR 3.x returns list of dicts; 2.x returns list of list of lines
    first = result[0]
    if isinstance(first, dict):
        # New API: result[0] = {'rec_texts': [...], 'rec_scores': [...], 'rec_boxes': [...]}
        texts = first.get("rec_texts", [])
        scores = first.get("rec_scores", [])
        boxes = first.get("rec_boxes", [])
        for text, conf, box in zip(texts, scores, boxes):
            if isinstance(box[0], (list, tuple)):
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
            else:
                xs = [box[0], box[2]]
                ys = [box[1], box[3]]
            items.append({
                "text": str(text).strip(),
                "conf": float(conf),
                "x1": float(min(xs)), "y1": float(min(ys)),
                "x2": float(max(xs)), "y2": float(max(ys)),
            })
    else:
        # Old API: result[0] = [[pts, (text, conf)], ...]
        for line in first:
            pts, (text, conf) = line
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            items.append({
                "text": text.strip(),
                "conf": float(conf),
                "x1": float(min(xs)), "y1": float(min(ys)),
                "x2": float(max(xs)), "y2": float(max(ys)),
            })
    return items


# ─────────────────────────────────────────────────────────────────────────────
# OCR helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _all_text(items: list[dict]) -> str:
    return " ".join(i["text"] for i in items)


def _find(items: list[dict], keyword: str) -> dict | None:
    """First item whose text contains keyword (case-insensitive)."""
    kw = keyword.lower()
    return next((i for i in items if kw in i["text"].lower()), None)


def _row_items(items: list[dict], y_mid: float, tol: float = 30) -> list[dict]:
    """Items whose vertical centre is within tol pixels of y_mid."""
    return sorted(
        [i for i in items if abs((i["y1"] + i["y2"]) / 2 - y_mid) < tol],
        key=lambda x: x["x1"],
    )


def _parse_date(text: str) -> str | None:
    """Extract first YYYY-MM-DD or DD.MM.YYYY and return as YYYY-MM-DD."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    return None


def _parse_date_range(text: str) -> tuple[str | None, str | None]:
    """Parse 'DD.MM.YYYY – DD.MM.YYYY' into (begin, end) YYYY-MM-DD strings."""
    m = re.search(
        r"(\d{1,2})[./](\d{1,2})[./](\d{4})\s*[-–]\s*(\d{1,2})[./](\d{1,2})[./](\d{4})",
        text,
    )
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.groups()
        return (
            f"{y1}-{mo1.zfill(2)}-{d1.zfill(2)}",
            f"{y2}-{mo2.zfill(2)}-{d2.zfill(2)}",
        )
    return None, None


def _extract_name_from_label(items: list[dict], label: str) -> str | None:
    """Find the text to the right of a label cell (e.g. 'Trainee:  Lucas Gil')."""
    anchor = _find(items, label)
    if not anchor:
        return None
    row = _row_items(items, (anchor["y1"] + anchor["y2"]) / 2)
    idx = next((i for i, it in enumerate(row) if label.lower() in it["text"].lower()), -1)
    if idx >= 0 and idx + 1 < len(row):
        return row[idx + 1]["text"] or None
    return None


def _text_block_after(items: list[dict], anchor: dict | None,
                      stop: dict | None = None) -> str | None:
    """Collect text in the vertical region [anchor.y2 … stop.y1]."""
    if not anchor:
        return None
    y_min = anchor["y2"]
    y_max = stop["y1"] if stop else anchor["y2"] + 250
    chunk = [
        i["text"] for i in sorted(items, key=lambda x: x["y1"])
        if i["y1"] >= y_min and i["y2"] <= y_max and i["text"] not in ("", "?")
    ]
    return " ".join(chunk) or None


# ─────────────────────────────────────────────────────────────────────────────
# Page-type detection
# ─────────────────────────────────────────────────────────────────────────────

_TYPE_KW: dict[str, list[str]] = {
    "CHECKLIST":  ["Training Check List", "Preparation", "Finishing Check"],
    "EXAM":       ["Training Examination", "READ BELOW INSTRUCTIONS"],
    "EVAL":       ["Evaluation of Training", "General Assessment"],
    "SURVEY_S1":  ["SURVEY OF TRAINING", "설문조사", "설문 조사"],
    "SURVEY_S2":  ["중요하지 않다", "매우 중요하다", "보통이다"],
    "SURVEY_S3":  ["Coherent 교육과정", "Coherent 장비", "KEP 서비스", "Thank You"],
}


def _page_type(items: list[dict]) -> str:
    full = _all_text(items).lower()
    for ptype, keywords in _TYPE_KW.items():
        if any(kw.lower() in full for kw in keywords):
            return ptype
    return "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# OpenCV checkbox detection
# ─────────────────────────────────────────────────────────────────────────────

def _to_gray(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("L"))


def _checked_col(gray_strip: np.ndarray, n_cols: int = 5) -> int | None:
    """Return 1-based index of the most-marked column in a horizontal strip.

    The strip is divided into n_cols equal parts; the part with the highest
    density of dark pixels is considered 'checked'.
    Returns None if no mark is found.
    """
    _, binary = cv2.threshold(gray_strip, 180, 255, cv2.THRESH_BINARY_INV)
    h, w = binary.shape
    col_w = max(w // n_cols, 1)
    densities = []
    for c in range(n_cols):
        cell = binary[:, c * col_w: (c + 1) * col_w]
        density = float(cell.sum()) / max(cell.size * 255, 1)
        densities.append(density)
    if max(densities) < 0.008:   # no visible mark
        return None
    return int(np.argmax(densities)) + 1   # 1-indexed


def _score_grid(
    img: Image.Image,
    y_top: float,
    y_bot: float,
    x_left: float,
    x_right: float,
    n_rows: int,
    n_cols: int = 5,
    first_field: str = "eval_q1",
) -> dict[str, int | None]:
    """Divide a table region into (n_rows × n_cols) cells and detect marks.

    Coordinates are fractions of the image dimensions (0.0–1.0).
    Returns {field_name: score (1–n_cols) or None}.
    """
    gray = _to_gray(img)
    H, W = gray.shape
    y1, y2 = int(y_top * H), int(y_bot * H)
    x1, x2 = int(x_left * W), int(x_right * W)
    table = gray[y1:y2, x1:x2]
    th = table.shape[0]
    row_h = max(th // n_rows, 1)

    results: dict[str, int | None] = {}
    # Derive field name prefix from first_field (e.g. "eval_q" or "survey_q")
    prefix = re.sub(r"\d+$", "", first_field)
    start_num = int(re.search(r"\d+$", first_field).group())  # type: ignore

    for row in range(n_rows):
        ry1 = row * row_h + 2
        ry2 = (row + 1) * row_h - 2
        strip = table[max(ry1, 0): min(ry2, th), :]
        if strip.size == 0:
            results[f"{prefix}{start_num + row}"] = None
            continue
        results[f"{prefix}{start_num + row}"] = _checked_col(strip, n_cols)

    return results


def _score_horizontal_checks(
    img: Image.Image,
    y_top: float,
    y_bot: float,
    x_left: float,
    x_right: float,
    n_options: int = 5,
) -> list[int]:
    """Return [1/0, …] for n_options horizontally arranged checkboxes."""
    gray = _to_gray(img)
    H, W = gray.shape
    strip = gray[int(y_top * H): int(y_bot * H),
                 int(x_left * W): int(x_right * W)]
    if strip.size == 0:
        return [0] * n_options
    _, binary = cv2.threshold(strip, 180, 255, cv2.THRESH_BINARY_INV)
    h, w = binary.shape
    col_w = max(w // n_options, 1)
    result = []
    for c in range(n_options):
        cell = binary[:, c * col_w: (c + 1) * col_w]
        density = float(cell.sum()) / max(cell.size * 255, 1)
        result.append(1 if density > 0.012 else 0)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Per-page-type extractors
# ─────────────────────────────────────────────────────────────────────────────

def _extract_checklist(items: list[dict], img: Image.Image) -> dict:
    full = _all_text(items)
    record: dict[str, Any] = {"_class_level": True}

    # Class number
    m = re.search(r"Class\s*N[ro][.:)#]?\s*(\d{3,5})", full, re.I)
    if m:
        record["class_number"] = m.group(1)

    # Date range  (e.g. "26.01.2026 – 06.02.2026")
    begin, end = _parse_date_range(full)
    if begin:
        record["course_begin_date"] = begin
        record["course_end_date"] = end or begin

    # Training center: text in footer (below "Training Dept" line if present)
    footer_kw = _find(items, "Training Dept") or _find(items, "Göttingen") or _find(items, "GmbH")
    if footer_kw:
        record["training_center"] = footer_kw["text"]

    return record


def _extract_eval(items: list[dict], img: Image.Image) -> dict:
    full = _all_text(items)
    record: dict[str, Any] = {}

    # Trainee name  (after "Trainee (optional):" label)
    record["trainee_name"] = (
        _extract_name_from_label(items, "Trainee")
        or _extract_name_from_label(items, "Name")
    )

    # Date
    date = _parse_date(full)
    if date:
        record["course_begin_date"] = date
        record["course_end_date"] = date

    # Class number
    m = re.search(r"#\s*(\d{3,5})|[Cc]lass\s*N[ro][.:)#]?\s*(\d{3,5})", full)
    if m:
        record["class_number"] = m.group(1) or m.group(2)

    # Course description  (after "Class:" label)
    class_lbl = _find(items, "Class")
    if class_lbl:
        row = _row_items(items, (class_lbl["y1"] + class_lbl["y2"]) / 2)
        idx = next((i for i, it in enumerate(row) if "class" in it["text"].lower()), -1)
        if idx >= 0 and idx + 1 < len(row):
            record["training_course_description"] = row[idx + 1]["text"]

    # Trainee type
    m_type = re.search(r"\bFSE\b|Engineer|Technician|User|엔지니어|사용자", full, re.I)
    if m_type:
        record["trainee_type"] = m_type.group(0)

    # Organisation / account
    org_lbl = _find(items, "Organization") or _find(items, "Company") or _find(items, "Account")
    if org_lbl:
        row = _row_items(items, (org_lbl["y1"] + org_lbl["y2"]) / 2)
        idx = next((i for i, it in enumerate(row) if it is org_lbl), -1)
        if idx >= 0 and idx + 1 < len(row):
            record["trainee_account"] = row[idx + 1]["text"]

    # ── Eval Q1-Q15 checkboxes ────────────────────────────────────────────────
    # Locate header anchor ("I. General Assessment" or similar)
    header = _find(items, "General Assessment") or _find(items, "General")
    comment_section = _find(items, "Comments") or _find(items, "Recommendations")
    img_h = img.height

    y_top = (header["y2"] / img_h) if header else 0.18
    y_bot = (comment_section["y1"] / img_h) if comment_section else 0.72

    scores = _score_grid(
        img,
        y_top=y_top, y_bot=y_bot,
        x_left=0.44, x_right=0.98,
        n_rows=15, n_cols=5,
        first_field="eval_q1",
    )
    record.update(scores)

    # ── Comments Q16-Q18 ─────────────────────────────────────────────────────
    q16 = _find(items, "like the best") or _find(items, "like most") or _find(items, "좋았")
    q17 = _find(items, "dislike") or _find(items, "불만")
    q18 = _find(items, "improvement") or _find(items, "propose") or _find(items, "개선")

    record["comment_q16"] = _text_block_after(items, q16, q17)
    record["comment_q17"] = _text_block_after(items, q17, q18)
    record["comment_q18"] = _text_block_after(items, q18)

    return record


def _extract_survey_s1(items: list[dict], img: Image.Image) -> dict:
    """Survey Section I: Q1-Q9 individual checkbox questions."""
    full = _all_text(items)
    record: dict[str, Any] = {}

    # Header fields (same format as evaluation)
    record["trainee_name"] = (
        _extract_name_from_label(items, "Trainee")
        or _extract_name_from_label(items, "Name")
    )
    date = _parse_date(full)
    if date:
        record["course_end_date"] = date
        record["course_begin_date"] = date

    m = re.search(r"\b(\d{4})\b", full)
    if m:
        record["class_number"] = m.group(1)

    # Course name
    m_c = re.search(r"LB\s*750[^\n,]{0,20}", full, re.I)
    if m_c:
        record["training_course_description"] = m_c.group(0).strip()

    # ── Q1-Q8: vertical list of single-select checkboxes ─────────────────────
    # Heuristic: questions occupy roughly 20-85% of page height
    img_h, img_w = img.height, img.width
    scores_q1_q8 = _score_grid(
        img,
        y_top=0.18, y_bot=0.78,
        x_left=0.00, x_right=0.45,   # left column = question side
        n_rows=8, n_cols=4,           # typical 4 options per question
        first_field="survey_q1",
    )
    record.update(scores_q1_q8)

    # ── Q9 multi-select: 5 independent options ────────────────────────────────
    q9_anchor = next(
        (i for i in items if re.search(r"\b9[.)]\s|Q9\b", i["text"])), None
    )
    if q9_anchor:
        y_t = (q9_anchor["y1"] - 5) / img_h
        y_b = (q9_anchor["y2"] + 80) / img_h
        checked = _score_horizontal_checks(img, y_t, y_b, 0.05, 0.95, n_options=5)
    else:
        # Fallback: assume Q9 is in the bottom 20% of the page
        checked = _score_horizontal_checks(img, 0.78, 0.90, 0.05, 0.95, n_options=5)

    for opt, val in enumerate(checked, start=1):
        record[f"survey_q9_{opt}"] = val

    return record


def _extract_survey_s2(items: list[dict], img: Image.Image) -> dict:
    """Survey Section II: Likert-scale table Q10-Q39 (30 rows × 5 columns)."""
    full = _all_text(items)
    record: dict[str, Any] = {}

    # Header fields
    record["trainee_name"] = (
        _extract_name_from_label(items, "Trainee")
        or _extract_name_from_label(items, "Name")
    )

    # Locate top of table from scale-header text
    header_item = (
        _find(items, "중요하지 않다")
        or _find(items, "매우 중요하다")
        or _find(items, "보통이다")
    )
    img_h = img.height
    y_top = (header_item["y2"] / img_h + 0.01) if header_item else 0.20

    # ── Q10-Q39 Likert table ─────────────────────────────────────────────────
    # Checkbox columns occupy the right ~55 % of the page width
    scores = _score_grid(
        img,
        y_top=y_top, y_bot=0.97,
        x_left=0.43, x_right=0.98,
        n_rows=30, n_cols=5,
        first_field="survey_q10",
    )
    record.update(scores)

    return record


# ─────────────────────────────────────────────────────────────────────────────
# Public API  (mirrors ocr_extractor.py)
# ─────────────────────────────────────────────────────────────────────────────

def extract_data_from_image_local(img: Image.Image) -> list[dict[str, Any]]:
    """Extract training data from one page using local OCR only."""
    items = _run_ocr(img)
    ptype = _page_type(items)

    if ptype in ("EXAM", "SURVEY_S3", "UNKNOWN"):
        return [{"_skip": True}]

    if ptype == "CHECKLIST":
        return [_extract_checklist(items, img)]

    if ptype == "EVAL":
        rec = _extract_eval(items, img)
        return [rec] if rec.get("trainee_name") else [{"_skip": True}]

    if ptype == "SURVEY_S1":
        rec = _extract_survey_s1(items, img)
        return [rec] if rec.get("trainee_name") else [{"_skip": True}]

    if ptype == "SURVEY_S2":
        rec = _extract_survey_s2(items, img)
        return [rec] if rec.get("trainee_name") else [{"_skip": True}]

    return [{"_skip": True}]


def extract_data_from_pdf_local(
    pdf_path: str,
    status_callback=None,
) -> list[dict[str, Any]]:
    """Process every page with local OCR; return one merged record per trainee.

    Pages are processed in parallel using a thread pool.  PaddleOCR's C++
    inference engine releases the GIL, so threads give real concurrency here.
    The model is pre-warmed (single-threaded) before the pool starts so that
    all threads share the already-initialised singleton without racing.
    """
    import os
    from pdf_processor import pdf_to_images

    # Load all pages upfront (fast – poppler is not the bottleneck).
    pages = list(pdf_to_images(pdf_path))
    total = len(pages)

    # Pre-warm the OCR model once before spawning threads.
    _get_paddle()

    # Number of worker threads: default to CPU count, capped at page count.
    n_workers = min(os.cpu_count() or 2, total, 4)

    # Collect (page_num, records) pairs from each worker.
    futures_map: dict = {}
    page_records: list[dict[str, Any]] = []

    def _process(args: tuple[int, Any]) -> tuple[int, list[dict]]:
        page_num, img = args
        if status_callback:
            status_callback(f"페이지 {page_num}/{total} 처리 중... (로컬 OCR)")
        return page_num, extract_data_from_image_local(img)

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures_map = {
            pool.submit(_process, (i, img)): i
            for i, img in enumerate(pages, start=1)
        }
        for future in as_completed(futures_map):
            page_num, records = future.result()
            for rec in records:
                if rec.get("_skip"):
                    continue
                rec["_source_page"] = page_num
                rec["_source_file"] = str(pdf_path)
                page_records.append(rec)

    return merge_records(page_records)
