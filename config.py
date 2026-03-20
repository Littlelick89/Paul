"""Configuration settings for the Training Data Extractor."""

import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-opus-4-6"

# PDF processing — separate DPI per OCR mode
PDF_DPI_CLAUDE = 300  # Claude vision API: higher DPI improves checkbox/text detail
PDF_DPI_LOCAL  = 200  # PaddleOCR: 200 DPI stays within the 4000 px internal limit

# OCR mode: "claude" (API) | "local" (PaddleOCR+OpenCV) | "hybrid" (Claude text + OpenCV checkboxes)
OCR_MODE = "claude"

# ---------------------------------------------------------------------------
# Column index helper
# ---------------------------------------------------------------------------

def _col(idx: int) -> str:
    """Convert 1-based column index to Excel column letter(s).

    Examples: 1→A, 26→Z, 27→AA, 34→AH, 69→BQ
    """
    if idx <= 26:
        return chr(ord("A") + idx - 1)
    return chr(ord("A") + (idx - 1) // 26 - 1) + chr(ord("A") + (idx - 1) % 26)


# ---------------------------------------------------------------------------
# Excel column mapping  (69 columns total: A–BQ)
# ---------------------------------------------------------------------------

# A–H  Basic training info (cols 1–8)
_BASIC_FIELDS: dict[str, str] = {
    "class_number":                "A",
    "course_begin_date":           "B",
    "course_end_date":             "C",
    "training_center":             "D",
    "trainee_type":                "E",
    "trainee_account":             "F",
    "trainee_name":                "G",
    "training_course_description": "H",
}

# I–W  Evaluation of Training Course scores Q1–Q15 (cols 9–23)
_EVAL_SCORE_FIELDS: dict[str, str] = {f"eval_q{i}": _col(8 + i) for i in range(1, 16)}

# X–Z  Evaluation comments Q16–Q18 (cols 24–26)
_EVAL_COMMENT_FIELDS: dict[str, str] = {
    "comment_q16": "X",
    "comment_q17": "Y",
    "comment_q18": "Z",
}

# AA–BQ  Survey of Training (cols 27–69, 43 columns total)
#   AA–AH  Survey Q1–Q8   : single-select questions         (cols 27–34)
#   AI–AM  Survey Q9_1–Q9_5 : multi-select sub-options      (cols 35–39)
#   AN–BQ  Survey Q10–Q39  : Likert-scale table rows        (cols 40–69)
_SURVEY_FIELDS: dict[str, str] = {}
for _i in range(1, 9):       # Q1–Q8  → cols 27–34
    _SURVEY_FIELDS[f"survey_q{_i}"] = _col(26 + _i)
for _i in range(1, 6):       # Q9_1–Q9_5 → cols 35–39
    _SURVEY_FIELDS[f"survey_q9_{_i}"] = _col(34 + _i)
for _i in range(10, 40):     # Q10–Q39 → cols 40–69  (_col(30 + 10)=_col(40)=AN … _col(30+39)=_col(69)=BQ)
    _SURVEY_FIELDS[f"survey_q{_i}"] = _col(30 + _i)

# Combined map  (insertion-order preserved → A … BQ)
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
    **{f"survey_q{i}": f"Survey Q{i}" for i in range(1, 9)},
    **{f"survey_q9_{i}": f"Survey Q9_{i}" for i in range(1, 6)},
    **{f"survey_q{i}": f"Survey Q{i}" for i in range(10, 40)},
}

# Row to start writing data (row 1 = headers)
EXCEL_START_ROW = 2

# Fields that belong to the class as a whole (not individual trainees).
# When merging, class-level values take priority over values extracted from
# individual-trainee pages (which may show only the session end-date, etc.).
CLASS_LEVEL_FIELDS = {"class_number", "course_begin_date", "course_end_date", "training_center"}

# Shared folder path (UNC or mapped drive), e.g. r"\\server\share\Training"
SHARED_FOLDER_PATH = os.getenv("SHARED_FOLDER_PATH", "")
