"""Extract structured training data from document images using Claude API."""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic
from PIL import Image

import config
from pdf_processor import image_to_base64

_SYSTEM_PROMPT = """\
You are an expert document data extractor for Korean corporate training records.
Extract data from the provided training document image and return ONLY valid JSON.
The document may contain Korean and/or English text.

RESPONSE FORMAT RULES:
- If the page contains data for MULTIPLE trainees: return a JSON ARRAY of objects (one per trainee)
- If the page contains data for ONE trainee: return a single JSON object
- If the page is a cover page, blank page, table of contents, or has NO trainee-specific data: return {"_skip": true}

Extract ALL of the following fields that are visible on this page (use null for fields not present):

=== Basic Training Info ===
- class_number: Training batch/session number ONLY (e.g. "4059").
  Do NOT put course names or level text here.
- course_begin_date: Start date of the training course in YYYY-MM-DD format.
- course_end_date: End date of the training course in YYYY-MM-DD format.
  If only one date is shown (single-day course), use the same value as course_begin_date.
- training_center: Name or location of the training facility/center.
- trainee_type: Type/category of trainee (e.g. "Engineer", "Technician", "User", "엔지니어", "사용자").
- trainee_account: Company or organisation the trainee belongs to (계정/소속 회사).
- trainee_name: ONE individual trainee's full name only.
  If multiple trainees appear on the same page, create SEPARATE records for each person.
  Do NOT combine multiple names into one field.
- training_course_description: Short course name (e.g. "LB 750 Level C", "Line Beam 750 Level C").
  Keep it brief — do not paste full sentences.

=== Evaluation of Training Course (점수: 1점~5점 or similar scale) ===
- eval_q1 through eval_q15: Numeric scores for evaluation questions 1 to 15.
  Extract the score the trainee gave for each question number.
  Use null if a particular question number is not found on this page.

=== Evaluation Comments (주관식 텍스트 답변) ===
- comment_q16: Text answer for question 16 (e.g. "What did you like most?").
- comment_q17: Text answer for question 17 (e.g. "What did you dislike?").
- comment_q18: Text answer for question 18 (e.g. "What improvements would you suggest?").

=== Survey of Training (설문조사 점수) ===
- survey_q1 through survey_q39: Numeric scores for survey questions 1 to 39.
  Extract the score for each survey question number.
  Use null if a particular survey question is not found on this page.

IMPORTANT NOTES:
- Use the training SESSION date for course_begin_date / course_end_date, NOT dates from old certificates.
- score fields must be NUMERIC only (e.g. 4, 3.5, 80). Never put text like "Level C" in a score field.
- If a page has evaluation Q1-Q15 but no survey data, leave all survey_q fields as null (and vice versa).

Return ONLY the JSON object or array, no markdown fences, no explanation.
"""


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
        max_tokens=2048,
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
                        "text": "Extract all training data fields from this document.",
                    },
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Strip accidental markdown fences
    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        parsed = json.loads(raw)
        # Normalise to a list so callers always get list[dict]
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except json.JSONDecodeError:
        return [{"_raw_response": raw}]


def merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge page-level records into one record per trainee.

    Records sharing the same (class_number, trainee_name) key are merged by
    taking the first non-null value for each field.  Records where both key
    fields are null are kept as-is (they cannot be de-duplicated).
    """
    merged: dict[tuple, dict[str, Any]] = {}
    ungrouped: list[dict[str, Any]] = []

    for record in records:
        class_num = record.get("class_number")
        name = record.get("trainee_name")

        if class_num is None and name is None:
            ungrouped.append(record)
            continue

        key = (class_num, name)
        if key not in merged:
            merged[key] = dict(record)
        else:
            # Fill in any null fields from this record
            for field, value in record.items():
                if value is not None and merged[key].get(field) is None:
                    merged[key][field] = value

    return list(merged.values()) + ungrouped


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
            record["_source_page"] = page_num
            record["_source_file"] = str(pdf_path)
            page_records.append(record)

    return merge_records(page_records)
