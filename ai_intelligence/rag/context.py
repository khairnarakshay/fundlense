# ai_intelligence/rag/context.py
"""Turns retrieved chunks into (a) the prompt block and (b) the citations returned to the client."""
from __future__ import annotations

from ai_intelligence.rag.retrieval import RetrievedChunk


def format_knowledge_context(chunks: list[RetrievedChunk]) -> tuple[str, list[dict]]:
    """
    Numbered excerpts inside <knowledge_base> tags, so the model can cite [1], [2].
    The closing tag is stripped from chunk text, so a document cannot break out of
    its delimiter and pose as instructions.
    """
    if not chunks:
        return "", []
    lines, citations = ["<knowledge_base>"], []
    for number, chunk in enumerate(chunks, start=1):
        label = chunk.document_title + (f", {chunk.version}" if chunk.version else "")
        text = chunk.content.replace("</knowledge_base>", "").replace("<knowledge_base>", "")
        lines.append(f"[{number}] {label} ({chunk.doc_type})\n{text}\n")
        citations.append({"number": number, "title": chunk.document_title, "source": chunk.source,
                          "doc_type": chunk.doc_type, "version": chunk.version, "chunk_index": chunk.chunk_index})
    lines.append("</knowledge_base>")
    return "\n".join(lines), citations