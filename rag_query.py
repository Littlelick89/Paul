"""RAG query engine — retrieval + Claude generation."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import config
from rag_ingest import _get_chroma_collection, _embed


_RAG_SYSTEM_PROMPT = """\
You are an expert assistant for Coherent corporate training and laser equipment documentation.
Answer the user's question using ONLY the context passages provided below.

Rules:
- If the answer is in the context, provide a clear, accurate answer and cite your sources.
- If the context does not contain enough information to answer confidently, say so honestly.
- Always respond in the same language as the user's question (Korean or English).
- Format your answer clearly. Use bullet points or numbered lists when helpful.
- At the end of your answer, cite the source documents and page numbers:
  Korean questions: [출처: filename.pdf p.N]
  English questions: [Source: filename.pdf p.N]
"""


def query_rag(
    question: str,
    client,
    top_k: int | None = None,
    conversation_history: list[dict] | None = None,
) -> dict:
    """Retrieve relevant chunks and generate an answer with Claude.

    Returns {"answer": str, "sources": list[{"filename", "page", "text_snippet", "relevance_score"}]}
    """
    if top_k is None:
        top_k = config.RAG_TOP_K

    collection = _get_chroma_collection()

    q_embedding = _embed([question])[0]

    results = collection.query(
        query_embeddings=[q_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not documents:
        return {
            "answer": (
                "죄송합니다. 현재 지식 베이스에 관련 문서가 없습니다. "
                "먼저 관리자 페이지에서 PDF 문서를 업로드해 주세요.\n\n"
                "Sorry, no documents are in the knowledge base yet. "
                "Please upload PDF documents via the Admin page first."
            ),
            "sources": [],
        }

    context_parts = []
    sources = []

    for i, (doc_text, meta, dist) in enumerate(
        zip(documents, metadatas, distances), start=1
    ):
        filename = meta.get("source_filename", "unknown")
        page_num = meta.get("page_num", "?")
        context_parts.append(
            f"[Context {i}] Source: {filename}, Page {page_num}\n{doc_text}"
        )
        sources.append(
            {
                "filename": filename,
                "page": page_num,
                "text_snippet": doc_text[:200] + ("..." if len(doc_text) > 200 else ""),
                "relevance_score": round(1.0 - dist, 3),
            }
        )

    context_block = "\n\n---\n\n".join(context_parts)
    user_message_text = (
        f"Context passages:\n\n{context_block}\n\n"
        f"---\n\nQuestion: {question}"
    )

    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history[-10:])
    messages.append({"role": "user", "content": user_message_text})

    try:
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2048,
            system=_RAG_SYSTEM_PROMPT,
            messages=messages,
        )
        answer = response.content[0].text.strip()
    except Exception as exc:
        answer = f"[오류] Claude API 호출 실패: {exc}"

    # De-duplicate sources by (filename, page)
    seen: set[tuple] = set()
    unique_sources = []
    for s in sources:
        key = (s["filename"], s["page"])
        if key not in seen:
            seen.add(key)
            unique_sources.append(s)

    return {"answer": answer, "sources": unique_sources}
