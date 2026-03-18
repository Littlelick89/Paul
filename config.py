"""Configuration settings for the Training Data Extractor."""

import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-opus-4-6"

# PDF processing
PDF_DPI = 200  # Resolution for PDF-to-image conversion

# Excel column mapping — edit these to match your actual Excel template
EXCEL_COLUMN_MAP = {
    "class_number":      "A",
    "case_number":       "B",
    "trainee_name":      "C",
    "date":              "D",
    "training_content":  "E",
    "score":             "F",
    "evaluation_score":  "G",
    "feedback_comments": "H",
}

# Row to start writing data (1-indexed); rows above are treated as headers
EXCEL_START_ROW = 2

# Shared folder path (UNC or mapped drive), e.g. r"\\server\share\Training"
SHARED_FOLDER_PATH = os.getenv("SHARED_FOLDER_PATH", "")
