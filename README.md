# Training Data Extractor

스캔된 PDF 교육 문서에서 데이터를 자동 추출하여 Excel 파일에 저장하는 자동화 도구입니다.

## 작동 방식

```
스캔 PDF → 이미지 변환 → Claude Vision OCR → 구조화된 데이터 → Excel 저장
```

## 설치 (Windows)

### 1. Python 3.10 이상 설치

### 2. Poppler 설치 (PDF → 이미지 변환에 필요)
- https://github.com/oschwartz10612/poppler-windows/releases 에서 다운로드
- 압축 해제 후 `bin` 폴더를 시스템 PATH에 추가

### 3. 패키지 설치
```bash
pip install -r requirements.txt
```

### 4. API Key 설정
`.env.example`을 `.env`로 복사하고 API Key 및 공유 폴더 경로 입력:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
SHARED_FOLDER_PATH=\\server\Training\output.xlsx
```

## 실행
```bash
python main.py
```

## Excel 컬럼 매핑 변경

`config.py`의 `EXCEL_COLUMN_MAP`을 수정하여 실제 엑셀 템플릿 구조에 맞게 조정하세요:

```python
EXCEL_COLUMN_MAP = {
    "class_number":      "A",   # 교육 회차
    "case_number":       "B",   # 케이스 번호
    "trainee_name":      "C",   # 교육생 이름
    "date":              "D",   # 날짜
    "training_content":  "E",   # 교육 내용
    "score":             "F",   # 점수
    "evaluation_score":  "G",   # 평가 점수
    "feedback_comments": "H",   # 피드백
}
```

## 파일 구조

| 파일 | 역할 |
|------|------|
| `main.py` | GUI 메인 애플리케이션 |
| `config.py` | 설정 (컬럼 매핑, 모델, DPI 등) |
| `pdf_processor.py` | PDF → 이미지 변환 |
| `ocr_extractor.py` | Claude API 호출 및 데이터 파싱 |
| `excel_writer.py` | Excel 파일 쓰기 |
