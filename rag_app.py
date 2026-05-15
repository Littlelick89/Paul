"""Flask web application for the RAG Education Q&A system.

Run:
    python rag_app.py

Endpoints:
    GET  /                           -> chat UI
    POST /api/chat                   -> {question} -> {answer, sources}
    GET  /admin                      -> admin document-management UI
    POST /api/upload                 -> multipart PDF -> {chunks_added, filename}
    GET  /api/documents              -> [{filename, chunk_count, upload_time}, ...]
    DELETE /api/documents/<filename> -> {deleted_chunks, filename}
"""

from __future__ import annotations

import os
import sys
import shutil
import tempfile
from pathlib import Path

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from flask import Flask, request, jsonify, render_template, session

import anthropic
import config
from rag_ingest import ingest_document, list_documents, delete_document
from rag_query import query_rag

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder=str(_HERE / "templates"))
app.secret_key = os.urandom(24)

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

_ALLOWED_EXT = {".pdf"}


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in _ALLOWED_EXT


# ---------------------------------------------------------------------------
# Chat routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()

    if not question:
        return jsonify({"error": "question is required"}), 400

    history: list[dict] = session.get("history", [])
    result = query_rag(question, _client, conversation_history=history)

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": result["answer"]})
    session["history"] = history[-10:]

    return jsonify(result)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file field in request"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    if not _allowed_file(f.filename):
        return jsonify({"error": "PDF 파일만 허용됩니다"}), 400

    suffix = Path(f.filename).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        f.save(tmp_path)

    # Rename temp file to original filename so pdf_path.name is correct
    final_path = Path(tempfile.gettempdir()) / f.filename
    try:
        shutil.move(str(tmp_path), str(final_path))

        chunks_added = ingest_document(
            final_path,
            client=_client,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    except Exception as exc:
        return jsonify({"error": f"처리 실패: {exc}"}), 500
    finally:
        final_path.unlink(missing_ok=True)

    return jsonify({"chunks_added": chunks_added, "filename": f.filename})


@app.route("/api/documents", methods=["GET"])
def api_documents():
    try:
        return jsonify(list_documents())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/documents/<path:filename>", methods=["DELETE"])
def api_delete_document(filename: str):
    try:
        deleted = delete_document(filename)
        return jsonify({"deleted_chunks": deleted, "filename": filename})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("RAG Education Q&A Server")
    print("  Chat:  http://localhost:5000/")
    print("  Admin: http://localhost:5000/admin")
    print("=" * 60)

    try:
        from rag_ingest import _get_chroma_collection, _get_embedding_model
        print("ChromaDB 연결 중...", end=" ", flush=True)
        _get_chroma_collection()
        print("OK")
        print("임베딩 모델 로딩 중...", end=" ", flush=True)
        _get_embedding_model()
        print("OK")
    except Exception as exc:
        print(f"\n[WARN] Startup warmup failed: {exc}")

    app.run(host="0.0.0.0", port=5000, debug=False)
