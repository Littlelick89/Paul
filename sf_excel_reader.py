"""Read training data from an Excel file and map to Salesforce fields."""

from __future__ import annotations

from pathlib import Path

import openpyxl

import config as excel_cfg
import sf_config as sf_cfg


def read_excel(file_path: str | Path) -> list[dict]:
    """Read all data rows from the Excel file and return SF-ready records.

    - Row 1 is treated as the header row and skipped.
    - Completely empty rows are skipped.
    - Each record dict uses Salesforce field API names as keys.

    Args:
        file_path: Path to the .xlsx file produced by the OCR program.

    Returns:
        List of dicts ready to be inserted into Salesforce.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If no data rows are found.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    # Build column-letter → excel_field_key reverse map
    letter_to_key: dict[str, str] = {
        col_letter: field_key
        for field_key, col_letter in excel_cfg.EXCEL_COLUMN_MAP.items()
    }

    records: list[dict] = []

    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row_idx == 1:
            continue  # skip header

        # Skip completely empty rows
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        sf_record: dict = {}
        for col_idx, cell_value in enumerate(row, start=1):
            col_letter = excel_cfg._col(col_idx)
            excel_key = letter_to_key.get(col_letter)
            if excel_key is None:
                continue  # column beyond our schema

            sf_field = sf_cfg.SF_FIELD_MAP.get(excel_key)
            if sf_field is None:
                continue  # not mapped to SF

            if cell_value is not None and str(cell_value).strip() != "":
                sf_record[sf_field] = cell_value

        if sf_record:
            records.append(sf_record)

    wb.close()

    if not records:
        raise ValueError("엑셀 파일에 업로드할 데이터 행이 없습니다.")

    return records


def preview_records(records: list[dict], max_rows: int = 5) -> str:
    """Return a human-readable preview string of the first N records."""
    lines: list[str] = [f"총 {len(records)}행 로드됨. 상위 {min(max_rows, len(records))}행 미리보기:\n"]
    for i, rec in enumerate(records[:max_rows], start=1):
        name = rec.get("Trainee_Name__c", "(이름 없음)")
        cls  = rec.get("Class_Number__c", "?")
        fields = len(rec)
        lines.append(f"  [{i}] {name}  |  Class: {cls}  |  필드수: {fields}")
    return "\n".join(lines)
