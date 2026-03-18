"""Configuration settings for the Training Data Extractor."""

import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-opus-4-6"

# PDF processing
PDF_DPI = 200  # Resolution for PDF-to-image conversion

# ---------------------------------------------------------------------------
# Excel column mapping
# ---------------------------------------------------------------------------
# Basic training info (A–H)
_BASIC_FIELDS = {
    "class_number":                "A",
    "course_begin_date":           "B",
    "course_end_date":             "C",
    "training_center":             "D",
    "trainee_type":                "E",
    "trainee_account":             "F",
    "trainee_name":                "G",
    "training_course_description": "H",
}

# Evaluation of Training course scores Q1–Q15 (I–W)
_EVAL_SCORE_FIELDS = {f"eval_q{i}": chr(ord("I") + i - 1) for i in range(1, 16)}

# Evaluation comments Q16–Q18 (X–Z)
_EVAL_COMMENT_FIELDS = {
    "comment_q16": "X",
    "comment_q17": "Y",
    "comment_q18": "Z",
}

# Survey of Training scores Q1–Q39 (AA–BM)
def _survey_col(n: int) -> str:
    """Return the Excel column letter for survey question n (1-indexed).

    Survey Q1 → AA (col 27), Q26 → AZ (col 52), Q27 → BA (col 53), Q39 → BM (col 65).
    """
    col_index = 26 + n  # AA=27, AB=28, …, AZ=52, BA=53, …, BM=65
    first = chr(ord("A") + (col_index - 1) // 26 - 1)
    second = chr(ord("A") + (col_index - 1) % 26)
    return first + second

_SURVEY_FIELDS = {f"survey_q{i}": _survey_col(i) for i in range(1, 40)}

# Combined column map (insertion-order preserved → A, B, … BM)
EXCEL_COLUMN_MAP: dict[str, str] = {
    **_BASIC_FIELDS,
    **_EVAL_SCORE_FIELDS,
    **_EVAL_COMMENT_FIELDS,
    **_SURVEY_FIELDS,
}

# Human-readable header labels for row 1
EXCEL_HEADERS: dict[str, str] = {
    "class_number":                "Class Number",
    "course_begin_date":           "Course Begin Date",
    "course_end_date":             "Course End Date",
    "training_center":             "Training Center",
    "trainee_type":                "Trainee Type",
    "trainee_account":             "Trainee (Account)",
    "trainee_name":                "Trainee Name",
    "training_course_description": "Training Course Description",
    **{f"eval_q{i}": f"Q{i} Score" for i in range(1, 16)},
    "comment_q16": "Q16 Comment",
    "comment_q17": "Q17 Comment",
    "comment_q18": "Q18 Comment",
    **{f"survey_q{i}": f"Survey Q{i}" for i in range(1, 40)},
}

# Row to start writing data (row 1 = headers)
EXCEL_START_ROW = 2

# Shared folder path (UNC or mapped drive), e.g. r"\\server\share\Training"
SHARED_FOLDER_PATH = os.getenv("SHARED_FOLDER_PATH", "")
