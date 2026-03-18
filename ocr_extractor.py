"""Extract structured training data from document images using Claude API."""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic
from PIL import Image

import config
from pdf_processor import image_to_base64

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
# Core extraction
# ---------------------------------------------------------------------------

def extract_data_from_image(
    img: Image.Image,
    client: anthropic.Anthropic | None = None,
) -> list[dict[str, Any]]:
    """Send *img* to Claude vision and return a list of extracted field dicts."""
    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    b64 = image_to_base64(img)

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract all training data fields from this document page.",
                    },
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [{"_raw_response": raw}]


# ---------------------------------------------------------------------------
# Merge helpers
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
# PDF-level entry point
# ---------------------------------------------------------------------------

def extract_data_from_pdf(
    pdf_path: str,
    client: anthropic.Anthropic | None = None,
    status_callback=None,
) -> list[dict[str, Any]]:
    """Process every page of *pdf_path* and return one merged record per trainee."""
    from pdf_processor import pdf_to_images

    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    page_records: list[dict[str, Any]] = []
    for page_num, img in enumerate(pdf_to_images(pdf_path), start=1):
        if status_callback:
            status_callback(f"페이지 {page_num} 처리 중...")

        records = extract_data_from_image(img, client=client)
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
