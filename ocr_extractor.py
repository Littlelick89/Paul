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
Extract data from the provided training document image and return ONLY a valid JSON object.
The document may contain Korean and/or English text.

Extract the following fields (use null if a field is not found):
- class_number: Training class / course number (교육 회차 or 클래스 번호)
- case_number: Case number (케이스 번호)
- trainee_name: Trainee full name (교육생 이름)
- date: Training date in YYYY-MM-DD format (교육 날짜)
- training_content: Main training subject or topic (교육 내용/주제)
- score: Raw score or grade (점수/성적)
- evaluation_score: Evaluation / assessment score (평가 점수)
- feedback_comments: Any feedback or comment text (피드백/의견)

Return ONLY the JSON object, no markdown fences, no explanation.
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
        return json.loads(raw)
    except json.JSONDecodeError:
        # Return whatever we got so the caller can log / review it
        return {"_raw_response": raw}


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
        data = extract_data_from_image(img, client=client)
        data["_source_page"] = page_num
        data["_source_file"] = str(pdf_path)
        results.append(data)

    return results
