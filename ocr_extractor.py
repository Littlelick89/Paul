"""Extract structured training data from document images using Claude API."""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic
from PIL import Image, ImageEnhance

import config
from pdf_processor import image_to_base64_with_type

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert document data extractor for Korean/English corporate training records.
Return ONLY valid JSON — no markdown fences, no explanation.

════════════════════════════════════════════════════════
RESPONSE FORMAT
════════════════════════════════════════════════════════
• Single JSON object  → page has data for ONE trainee
• JSON array          → page has data for MULTIPLE trainees (one object per person)
• {"_skip": true}     → blank page or page with no extractable data

ALWAYS include "_page_type" in every non-skip response.
  "_page_type": one of "CHECKLIST" | "EVAL" | "SURVEY_S1" | "SURVEY_S2" | "EXAM" | "SURVEY_S3" | "UNKNOWN"

SPECIAL CASE — Training Check List / Preparation & Finishing Check List
  These pages show a table of topics with columns of checkmarks for the whole class.
  Return ONE object with ONLY the class-level fields below and "_class_level": true.
  Leave trainee_name as null — do NOT create one record per listed trainee name.

════════════════════════════════════════════════════════
FIELDS  (use null for any field not visible on this page)
════════════════════════════════════════════════════════

── Basic Training Info ──────────────────────────────────
class_number                 Batch/session NUMBER only (e.g. "4059"). Never put course names or level text here.
course_begin_date            Course start date YYYY-MM-DD. On Check List pages read the full date range (e.g. "26.01.2026 – 06.02.2026").
course_end_date              Course end date YYYY-MM-DD.
training_center              Full name of the training facility or location.
trainee_type                 Category of trainee (e.g. "FSE", "Engineer", "User"). null if not shown.
trainee_account              Company/organisation the trainee belongs to.
trainee_name                 ONE trainee's SHORT ENGLISH name (e.g. "Lucas Gil", "Rob Lee").
                             • Read the "Trainee (optional):" or "Name:" field in the form header.
                             • Use the short/informal name, NOT the formal checklist format "Last, First(nick) (Korean)".
                             • For pages listing multiple people, return a separate JSON object for each.
training_course_description  Short course name (e.g. "LB 750 Level C"). Do not paste full sentences.

── Evaluation of Training Course  (Q1–Q15) ──────────────
eval_q1 … eval_q15
  Each question has 5 checkbox options in a row (Likert-style).
  Find the checked box and record its column number: 1 (leftmost) … 5 (rightmost).
  Use null if the question is not on this page.

── Evaluation Comments  (Q16–Q18) ───────────────────────
comment_q16   Text for "What did you like the most?" (주관식 Q16)
comment_q17   Text for "What did you dislike the most?" (주관식 Q17)
comment_q18   Text for "What improvements would you propose?" (주관식 Q18)

── Survey of Training ────────────────────────────────────
The Survey form is divided into sections.

▸ SECTION I — Individual checkbox questions (Survey Q1–Q9)
  survey_q1 … survey_q8
    Each question has one or more checkbox options.
    Record the selected option number (1, 2, 3 …) or 1=checked / 0=not-checked.

  survey_q9_1, survey_q9_2, survey_q9_3, survey_q9_4, survey_q9_5
    Q9 allows MULTIPLE simultaneous selections (5 independent options).
    For EACH option: 1 = selected/checked, 0 = not selected.

▸ SECTION II — Likert-scale table (Survey Q10–Q39)
  This section is a TABLE:
    • Rows  = survey questions/items (30 rows → Q10 to Q39)
    • Columns = 5 rating options with this meaning:
        Column 1 → "전혀 중요하지 않다"  (Not at all important) → score 1
        Column 2 → "중요하지 않다"        (Not important)         → score 2
        Column 3 → "보통이다"             (Neutral)               → score 3
        Column 4 → "중요하다"             (Important)             → score 4
        Column 5 → "매우 중요하다"        (Very important)        → score 5

  HOW TO READ: For each row, locate the checkmark (✓, ✗, ■, ●, circled number,
  or any mark) and determine which column (1–5) it falls in. That column number
  is the score for that question.

  survey_q10 = row 1, survey_q11 = row 2, … survey_q39 = row 30.
  Extract ALL 30 rows. If a row has no mark, use null.

════════════════════════════════════════════════════════
IMPORTANT RULES
════════════════════════════════════════════════════════
• score/eval fields must be NUMERIC (e.g. 4, 3, 80.5). Never put text like "Level C".
• Do NOT confuse the training check-list completion checkmarks with evaluation scores.
• Handwritten exam answer pages: return {"_skip": true} — they contain no structured scores.
• For Survey Section I vs Section II: Section I is a list of individual questions,
  Section II is a grid/table format. They are on different pages or clearly separated.
"""

# ---------------------------------------------------------------------------
# Page-type detection
# ---------------------------------------------------------------------------

_TYPE_KW: dict[str, list[str]] = {
    "CHECKLIST":  ["Training Check List", "Preparation", "Finishing Check"],
    "EXAM":       ["Training Examination", "READ BELOW INSTRUCTIONS"],
    "EVAL":       ["Evaluation of Training", "General Assessment"],
    "SURVEY_S1":  ["SURVEY OF TRAINING", "설문조사", "설문 조사"],
    "SURVEY_S2":  ["중요하지 않다", "매우 중요하다", "보통이다"],
    "SURVEY_S3":  ["Coherent 교육과정", "Coherent 장비", "KEP 서비스", "Thank You"],
}


def _guess_page_type(records: list[dict]) -> str:
    """Infer page type from Claude's own _page_type field, then heuristics."""
    for r in records:
        pt = r.get("_page_type", "")
        if pt and pt not in ("", "UNKNOWN"):
            return pt
    # Heuristic fallback
    r0 = records[0] if records else {}
    if r0.get("_class_level"):
        return "CHECKLIST"
    if any(r0.get(f"eval_q{i}") is not None for i in range(1, 16)):
        return "EVAL"
    if any(r0.get(f"survey_q{i}") is not None for i in range(10, 40)):
        return "SURVEY_S2"
    if any(r0.get(f"survey_q{i}") is not None for i in range(1, 9)):
        return "SURVEY_S1"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Page-type specific retry hints
# ---------------------------------------------------------------------------

_PAGE_HINTS: dict[str, str] = {
    "EVAL": (
        "This is an [Evaluation of Training Course] page.\n"
        "PRIORITY: Extract eval_q1 through eval_q15 (Q1–Q15 checkbox scores 1–5).\n"
        "The checkbox grid has 15 rows × 5 columns. For EVERY row, locate the marked cell "
        "(✓, ✗, ■, filled circle, handwritten mark) and record its 1-based column number.\n"
        "Also extract comment_q16, comment_q17, comment_q18 from open-text areas.\n"
        "A zoomed crop of the checkbox area is provided as the second image — use it for precise column detection."
    ),
    "SURVEY_S1": (
        "This is a [Survey of Training — Section I] page.\n"
        "PRIORITY: Extract survey_q1 through survey_q8 (selected option number) "
        "and survey_q9_1 through survey_q9_5 (1=checked, 0=not checked).\n"
        "A zoomed crop of the checkbox area is provided as the second image — use it.\n"
        "Also extract header fields: trainee_name, course dates, class_number."
    ),
    "SURVEY_S2": (
        "This is a [Survey of Training — Section II Likert table] page.\n"
        "PRIORITY: Extract survey_q10 through survey_q39 (30 rows × 5 columns).\n"
        "For EVERY row find the marked cell and record its column number (1–5). "
        "Do NOT skip rows — use null only when truly unmarked.\n"
        "A zoomed crop of the Likert table is provided as the second image — use it for precise column detection."
    ),
    "CHECKLIST": (
        "This is a [Training Check List] page.\n"
        "Extract ONLY class-level fields: class_number, course_begin_date, course_end_date, training_center.\n"
        "Set _class_level to true. Do NOT create per-trainee records."
    ),
}

_DEFAULT_HINT = "Extract all training data fields from this document page."

# ---------------------------------------------------------------------------
# Checkbox crop regions  (x1_frac, y1_frac, x2_frac, y2_frac)
# ---------------------------------------------------------------------------

_CHECKBOX_CROP: dict[str, tuple[float, float, float, float]] = {
    "EVAL":      (0.42, 0.16, 1.00, 0.74),
    "SURVEY_S1": (0.00, 0.16, 0.48, 0.92),
    "SURVEY_S2": (0.40, 0.14, 1.00, 0.98),
}

# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def _enhance_contrast(img: Image.Image, factor: float = 2.5) -> Image.Image:
    """Boost contrast to make checkbox marks more visible."""
    gray = img.convert("L")
    return ImageEnhance.Contrast(gray).enhance(factor).convert("RGB")


def _crop_region(
    img: Image.Image, x1f: float, y1f: float, x2f: float, y2f: float
) -> Image.Image:
    """Crop image by fractional (0–1) coordinates."""
    W, H = img.size
    return img.crop((int(x1f * W), int(y1f * H), int(x2f * W), int(y2f * H)))


# ---------------------------------------------------------------------------
# Null-ratio check
# ---------------------------------------------------------------------------


def _checkbox_null_ratio(records: list[dict], page_type: str) -> float:
    """Return fraction of expected checkbox fields that are null."""
    if page_type == "EVAL":
        fields = [f"eval_q{i}" for i in range(1, 16)]
    elif page_type == "SURVEY_S1":
        fields = [f"survey_q{i}" for i in range(1, 9)]
    elif page_type == "SURVEY_S2":
        fields = [f"survey_q{i}" for i in range(10, 40)]
    else:
        return 0.0

    values = [r.get(f) for r in records for f in fields]
    if not values:
        return 0.0
    return sum(1 for v in values if v is None) / len(values)


# ---------------------------------------------------------------------------
# Core Claude API call
# ---------------------------------------------------------------------------


def _call_claude(
    images: list[Image.Image],
    client: anthropic.Anthropic,
    hint: str = _DEFAULT_HINT,
) -> list[dict[str, Any]]:
    """Send one or more images to Claude and return parsed records."""
    content: list[dict] = []
    for img in images:
        b64, media_type = image_to_base64_with_type(img)
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
    content.append({"type": "text", "text": hint})

    try:
        message = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.BadRequestError as exc:
        print(f"[ERROR] Claude API 400: {exc}")
        return [{"_skip": True}]

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [{"_raw_response": raw}]


# ---------------------------------------------------------------------------
# Main extraction with retry logic
# ---------------------------------------------------------------------------


def extract_data_from_image(
    img: Image.Image,
    client: anthropic.Anthropic | None = None,
) -> list[dict[str, Any]]:
    """Send *img* to Claude vision and return a list of extracted field dicts.

    Improvement pipeline:
      Pass 1 — full page, generic hint.
      If checkbox null-ratio > 50 %:
        Pass 2 — full page + contrast-enhanced checkbox crop, type-specific hint.
    """
    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # ── Pass 1: generic extraction ────────────────────────────────────────
    records = _call_claude([img], client, hint=_DEFAULT_HINT)

    if not records or all(r.get("_skip") for r in records):
        return records

    # ── Detect page type from Claude's own _page_type field ───────────────
    page_type = _guess_page_type(records)

    # ── Check null ratio; retry if needed ─────────────────────────────────
    null_ratio = _checkbox_null_ratio(records, page_type)
    if null_ratio > 0.5 and page_type in _PAGE_HINTS:
        print(
            f"[RETRY] null_ratio={null_ratio:.0%} on {page_type} page "
            "— retrying with crop + contrast"
        )
        images = [img]
        if page_type in _CHECKBOX_CROP:
            crop = _crop_region(img, *_CHECKBOX_CROP[page_type])
            images.append(_enhance_contrast(crop))

        records = _call_claude(images, client, hint=_PAGE_HINTS[page_type])

    return records


# ---------------------------------------------------------------------------
# Hybrid extraction  (Claude text fields + OpenCV checkboxes)
# ---------------------------------------------------------------------------


def extract_data_from_image_hybrid(
    img: Image.Image,
    client: anthropic.Anthropic | None = None,
    status_callback=None,
) -> list[dict[str, Any]]:
    """Hybrid mode: Claude API for text fields, PaddleOCR+OpenCV for checkboxes.

    Each engine does what it is best at:
      • Claude  → trainee_name, dates, comments, course info  (high accuracy)
      • OpenCV  → eval_q1–q15, survey_q1–q39  (pixel-level mark detection)

    Requires PaddleOCR + OpenCV to be installed (same as "local" mode).
    Falls back to Claude-only if local OCR is unavailable.
    """
    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    _CHECKBOX_FIELDS = (
        {f"eval_q{i}" for i in range(1, 16)}
        | {f"survey_q{i}" for i in range(1, 10)}
        | {f"survey_q9_{i}" for i in range(1, 6)}
        | {f"survey_q{i}" for i in range(10, 40)}
    )

    # ── Step 1: Claude extracts text/header fields ─────────────────────────
    text_hint = (
        "Extract ONLY text/header fields: trainee_name, class_number, course_begin_date, "
        "course_end_date, training_center, trainee_type, trainee_account, "
        "training_course_description, comment_q16, comment_q17, comment_q18, "
        "_class_level, _page_type.\n"
        "Set ALL checkbox/score fields (eval_q*, survey_q*) to null — "
        "they will be detected separately by a local vision engine."
    )
    claude_records = _call_claude([img], client, hint=text_hint)

    if not claude_records or all(r.get("_skip") for r in claude_records):
        return claude_records

    page_type = _guess_page_type(claude_records)

    # ── Step 2: local OCR extracts checkboxes ─────────────────────────────
    try:
        from local_ocr_extractor import extract_data_from_image_local  # lazy — avoids circular import
        local_records = extract_data_from_image_local(img, status_callback=status_callback)
    except Exception as exc:
        print(f"[HYBRID] Local OCR unavailable: {exc} — falling back to Claude-only")
        return claude_records

    # ── Step 3: merge — Claude text + OpenCV checkboxes ───────────────────
    merged: list[dict[str, Any]] = []
    for i, crec in enumerate(claude_records):
        rec = dict(crec)
        # Pick the matching local record (by index); if none, use first
        lrec = local_records[i] if i < len(local_records) else (local_records[0] if local_records else {})
        for k in _CHECKBOX_FIELDS:
            local_val = lrec.get(k)
            if local_val is not None:
                rec[k] = local_val
        merged.append(rec)

    return merged


# ---------------------------------------------------------------------------
# Merge helpers  (shared with local_ocr_extractor)
# ---------------------------------------------------------------------------


def merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge page-level records into one record per trainee.

    Strategy
    --------
    1. Records with ``_class_level: true`` supply class-wide fields
       (class_number, dates, training_center).  These fields win over values
       from individual pages, which often see only the session end-date.
    2. All other records are grouped by normalised trainee_name and merged via
       "first non-null wins" within each group.
    3. Class-level fields are then applied on top of each merged individual
       record (overwriting only the fields listed in config.CLASS_LEVEL_FIELDS).
    """
    class_info: dict[str, Any] = {}
    by_name: dict[str, dict[str, Any]] = {}

    for record in records:
        # ── Class-level records (Training Check List pages) ──────────────
        if record.get("_class_level"):
            for k, v in record.items():
                if not k.startswith("_") and v is not None and class_info.get(k) is None:
                    class_info[k] = v
            continue

        # ── Individual records ────────────────────────────────────────────
        name_raw = (record.get("trainee_name") or "").strip()
        if not name_raw:
            continue  # cannot assign to a trainee → discard

        key = name_raw.lower()
        if key not in by_name:
            by_name[key] = dict(record)
        else:
            # Fill missing fields from subsequent pages (first non-null wins)
            for k, v in record.items():
                if v is not None and by_name[key].get(k) is None:
                    by_name[key][k] = v

    # ── Apply class-level info to every individual record ─────────────────
    result: list[dict[str, Any]] = []
    for record in by_name.values():
        final = dict(record)
        for k, v in class_info.items():
            if v is None:
                continue
            if k in config.CLASS_LEVEL_FIELDS:
                final[k] = v          # class-level fields always win
            elif final.get(k) is None:
                final[k] = v          # fill other missing fields
        result.append(final)

    return result


# ---------------------------------------------------------------------------
# PDF-level entry points
# ---------------------------------------------------------------------------


def extract_data_from_pdf(
    pdf_path: str,
    client: anthropic.Anthropic | None = None,
    status_callback=None,
) -> list[dict[str, Any]]:
    """Process every page of *pdf_path* with Claude API; return one merged record per trainee."""
    from pdf_processor import pdf_to_images

    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    page_records: list[dict[str, Any]] = []
    for page_num, img in enumerate(pdf_to_images(pdf_path, dpi=config.PDF_DPI_CLAUDE), start=1):
        if status_callback:
            status_callback(f"페이지 {page_num} 처리 중... (Claude API, {config.PDF_DPI_CLAUDE} DPI)")

        records = extract_data_from_image(img, client=client)

        valid = [r for r in records if not r.get("_skip") and "_raw_response" not in r]
        if status_callback and valid:
            r0 = valid[0]
            ptype = r0.get("_page_type", "?")
            non_null = sum(1 for v in r0.values() if v is not None and not str(v).startswith("_"))
            status_callback(f"  → {len(valid)}명분 추출 | 페이지 유형: {ptype} | non-null 필드: {non_null}개")

        for record in records:
            if record.get("_skip"):
                continue
            if "_raw_response" in record:
                print(
                    f"[WARN] 파싱 실패 (페이지 {page_num}): "
                    f"{record['_raw_response'][:120]}"
                )
                continue
            record["_source_page"] = page_num
            record["_source_file"] = str(pdf_path)
            page_records.append(record)

    return merge_records(page_records)


def extract_data_from_pdf_hybrid(
    pdf_path: str,
    client: anthropic.Anthropic | None = None,
    status_callback=None,
) -> list[dict[str, Any]]:
    """Process every page with Hybrid mode (Claude text + OpenCV checkboxes)."""
    from pdf_processor import pdf_to_images

    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    page_records: list[dict[str, Any]] = []
    for page_num, img in enumerate(pdf_to_images(pdf_path, dpi=config.PDF_DPI_CLAUDE), start=1):
        if status_callback:
            status_callback(f"페이지 {page_num} 처리 중... (Hybrid)")

        records = extract_data_from_image_hybrid(img, client=client, status_callback=status_callback)

        valid = [r for r in records if not r.get("_skip") and "_raw_response" not in r]
        if status_callback and valid:
            r0 = valid[0]
            ptype = r0.get("_page_type", "?")
            non_null = sum(1 for v in r0.values() if v is not None and not str(v).startswith("_"))
            status_callback(f"  → {len(valid)}명분 추출 | 페이지 유형: {ptype} | non-null 필드: {non_null}개")

        for record in records:
            if record.get("_skip"):
                continue
            if "_raw_response" in record:
                print(
                    f"[WARN] 파싱 실패 (페이지 {page_num}): "
                    f"{record['_raw_response'][:120]}"
                )
                continue
            record["_source_page"] = page_num
            record["_source_file"] = str(pdf_path)
            page_records.append(record)

    return merge_records(page_records)
