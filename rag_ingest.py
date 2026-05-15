"""Document ingestion pipeline for the RAG Q&A module.

Pipeline:
  PDF → extract_text_from_pdf() → chunk_text() → embed → ChromaDB
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import config


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_chroma_client = None
_collection = None
_embedding_model = None


def _get_chroma_collection():
    global _chroma_client, _collection
    if _collection is not None:
        return _collection

    import chromadb

    db_path = str((_HERE / config.RAG_CHROMA_DB_PATH).resolve())
    _chroma_client = chromadb.PersistentClient(path=db_path)
    _collection = _chroma_client.get_or_create_collection(
        name=config.RAG_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(config.RAG_EMBEDDING_MODEL)
    return _embedding_model


def _embed(texts: list[str]) -> list[list[float]]:
    model = _get_embedding_model()
    return model.encode(texts, convert_to_numpy=True).tolist()


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

_DIGITAL_PDF_THRESHOLD = 50  # chars/page; below this → treat as scanned

_TEXT_EXTRACTION_PROMPT = (
    "Please extract all readable text from this document image. "
    "Return ONLY the plain text content, preserving paragraph structure. "
    "Do not add explanations, summaries, or formatting markers. "
    "If the page is blank or contains no readable text, return an empty string."
)


def extract_text_from_pdf(
    pdf_path: str | Path,
    client=None,
    status_callback: Callable[[str], None] | None = None,
) -> list[dict]:
    """Extract text from each page of a PDF.

    Returns [{"page_num": int, "text": str, "source_filename": str}, ...]

    Strategy:
      1. Try PyMuPDF for digital/text-based PDFs (>=_DIGITAL_PDF_THRESHOLD chars/page).
      2. Fall back to Claude Vision API for scanned pages.
    """
    pdf_path = Path(pdf_path)
    source_filename = pdf_path.name
    results: list[dict] = []

    # ── Attempt 1: PyMuPDF ──────────────────────────────────────────────
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        digital_pages: dict[int, str] = {}

        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if len(text) >= _DIGITAL_PDF_THRESHOLD:
                digital_pages[page_num] = text
            if status_callback:
                status_callback(f"PyMuPDF 페이지 {page_num}/{total_pages} 처리 중...")

        doc.close()

        for page_num, text in digital_pages.items():
            results.append(
                {"page_num": page_num, "text": text, "source_filename": source_filename}
            )

        if len(digital_pages) == total_pages:
            # All pages are digital — no need for Vision fallback
            return results

        scanned_page_nums = [p for p in range(1, total_pages + 1) if p not in digital_pages]

    except ImportError:
        scanned_page_nums = None  # treat all pages as scanned
        if status_callback:
            status_callback("PyMuPDF 없음 — Claude Vision 모드로 전환")

    # ── Attempt 2: Claude Vision for scanned pages ───────────────────────
    if scanned_page_nums is None or scanned_page_nums:
        from pdf_processor import pdf_to_images, image_to_base64_with_type

        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

        for page_num, img in enumerate(
            pdf_to_images(str(pdf_path), dpi=config.PDF_DPI_CLAUDE), start=1
        ):
            if scanned_page_nums is not None and page_num not in scanned_page_nums:
                continue

            if status_callback:
                status_callback(f"Claude Vision 페이지 {page_num} 처리 중...")

            b64, media_type = image_to_base64_with_type(img)
            try:
                message = client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": b64,
                                    },
                                },
                                {"type": "text", "text": _TEXT_EXTRACTION_PROMPT},
                            ],
                        }
                    ],
                )
                text = message.content[0].text.strip()
            except Exception as exc:
                print(f"[WARN] Claude Vision failed on page {page_num}: {exc}")
                text = ""

            if text:
                results.append(
                    {"page_num": page_num, "text": text, "source_filename": source_filename}
                )

    results.sort(key=lambda d: d["page_num"])
    return results


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(
    pages: list[dict],
    chunk_size: int = config.RAG_CHUNK_SIZE,
    overlap: int = config.RAG_CHUNK_OVERLAP,
) -> list[dict]:
    """Sliding-window character-level chunking. Chunks do not cross page boundaries."""
    chunks: list[dict] = []
    chunk_index = 0

    for page in pages:
        text = page["text"]
        if not text:
            continue

        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk_body = text[start:end].strip()
            if chunk_body:
                chunks.append(
                    {
                        "page_num": page["page_num"],
                        "text": chunk_body,
                        "source_filename": page["source_filename"],
                        "chunk_index": chunk_index,
                    }
                )
                chunk_index += 1
            start += chunk_size - overlap

    return chunks


# ---------------------------------------------------------------------------
# Full ingestion pipeline
# ---------------------------------------------------------------------------


def ingest_document(
    pdf_path: str | Path,
    client=None,
    status_callback: Callable[[str], None] | None = None,
) -> int:
    """Run the full ingestion pipeline for one PDF. Returns chunk count added."""
    pdf_path = Path(pdf_path)
    source_filename = pdf_path.name

    collection = _get_chroma_collection()

    existing = collection.get(where={"source_filename": source_filename}, limit=1)
    if existing["ids"]:
        raise ValueError(
            f"'{source_filename}'은(는) 이미 지식 베이스에 있습니다. "
            "먼저 삭제 후 다시 업로드하세요."
        )

    if status_callback:
        status_callback(f"텍스트 추출 중: {source_filename}")

    pages = extract_text_from_pdf(pdf_path, client=client, status_callback=status_callback)

    if not pages:
        raise RuntimeError(f"텍스트를 추출할 수 없습니다: {source_filename}")

    if status_callback:
        status_callback(f"청크 분할 중 ({len(pages)} 페이지)...")

    chunks = chunk_text(pages)

    if not chunks:
        raise RuntimeError(f"청크를 생성할 수 없습니다: {source_filename}")

    if status_callback:
        status_callback(f"임베딩 생성 중 ({len(chunks)} 청크)...")

    texts = [c["text"] for c in chunks]
    embeddings = _embed(texts)

    upload_time = datetime.now(timezone.utc).isoformat()
    ids = [f"{source_filename}::chunk::{c['chunk_index']}" for c in chunks]
    metadatas = [
        {
            "source_filename": c["source_filename"],
            "page_num": c["page_num"],
            "chunk_index": c["chunk_index"],
            "upload_time": upload_time,
        }
        for c in chunks
    ]

    batch_size = 500
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i : i + batch_size],
            embeddings=embeddings[i : i + batch_size],
            documents=texts[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    if status_callback:
        status_callback(f"완료: {len(chunks)} 청크가 저장되었습니다.")

    return len(chunks)


# ---------------------------------------------------------------------------
# Document management
# ---------------------------------------------------------------------------


def list_documents() -> list[dict]:
    """Return one summary dict per unique source_filename in ChromaDB."""
    collection = _get_chroma_collection()
    result = collection.get(include=["metadatas"])
    metadatas = result.get("metadatas") or []

    by_file: dict[str, dict] = {}
    for meta in metadatas:
        fname = meta.get("source_filename", "unknown")
        if fname not in by_file:
            by_file[fname] = {
                "filename": fname,
                "chunk_count": 0,
                "upload_time": meta.get("upload_time", ""),
            }
        by_file[fname]["chunk_count"] += 1

    return sorted(by_file.values(), key=lambda d: d["upload_time"], reverse=True)


def delete_document(source_filename: str) -> int:
    """Delete all chunks for *source_filename*. Returns count deleted."""
    collection = _get_chroma_collection()
    existing = collection.get(where={"source_filename": source_filename})
    ids_to_delete = existing.get("ids", [])

    if not ids_to_delete:
        raise ValueError(f"문서를 찾을 수 없습니다: '{source_filename}'")

    collection.delete(ids=ids_to_delete)
    return len(ids_to_delete)
