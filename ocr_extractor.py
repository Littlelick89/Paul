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

Extract the following fields (use null if a field is not found):
- class_number: The training batch/session NUMBER only (e.g. "4059").
  Do NOT put course names, levels, or "Level C" here. Only numeric or short alphanumeric batch IDs.
- case_number: Equipment or product case/serial number (e.g. "C0912010").
  This is typically an alphanumeric code starting with a letter (e.g. C, LB) identifying the equipment.
- trainee_name: ONE individual trainee's full name only.
  If multiple trainees appear on the same page (e.g. attendance sheet), create SEPARATE records for each.
  Do NOT combine multiple names into one field.
- date: The date this specific training SESSION was conducted, in YYYY-MM-DD format.
  Use the actual training date shown on the document header or title area.
  Do NOT use dates from old certification histories, previous test records, or issuance dates of past documents.
- training_content: Short course name or topic (e.g. "LB 750 Level C", "Line Beam 750 Level C").
  Keep it brief — do not include full sentences or paragraphs.
- score: Numeric test/exam score ONLY (e.g. 80.5, 69).
  Do NOT put level names like "Level C" or "C Level" here. Use null if no numeric score is present.
- evaluation_score: Numeric training satisfaction or self-evaluation score if present (e.g. 10). Use null if absent.
- feedback_comments: Text feedback, opinion, or comments written by the trainee.
  For survey/설문 pages, include the trainee's written responses.

Return ONLY the JSON object or array, no markdown fences, no explanation.
"""


def extract_data_from_image(
    img: Image.Image,
    client: anthropic.Anthropic | None = None,
) -> dict[str, Any]:
    """Send *img* to Claude vision and return extracted fields as a dict."""
    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    b64 = image_to_base64(img)

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
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


def extract_data_from_pdf(
    pdf_path: str,
    client: anthropic.Anthropic | None = None,
    status_callback=None,
) -> list[dict[str, Any]]:
    """Process every page of *pdf_path* and return a list of extracted records."""
    from pdf_processor import pdf_to_images

    if client is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    results: list[dict[str, Any]] = []
    for page_num, img in enumerate(pdf_to_images(pdf_path), start=1):
        if status_callback:
            status_callback(f"페이지 {page_num} 처리 중...")
        records = extract_data_from_image(img, client=client)
        for record in records:
            if record.get("_skip"):
                continue
            record["_source_page"] = page_num
            record["_source_file"] = str(pdf_path)
            results.append(record)

    return results
