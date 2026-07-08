"""
Admin ERP RAG service — hybrid retrieval (BM25 + dense vectors) over uploaded data.

Separate from the policy knowledge base in knowledge_base.py. Only used when an
admin enables RAG mode on the admin dashboard.
"""

from __future__ import annotations

import io
import json
import logging
import os
import pickle
import re
import shutil
import threading
import time
import traceback
from typing import Any, Literal

import pandas as pd
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

logger = logging.getLogger("taia.rag_service")

_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "admin_rag_store")
ADMIN_RAG_PERSIST_DIR = os.getenv("ADMIN_RAG_PERSIST_DIR", _BASE_DIR)
PERSIST_DIR = ADMIN_RAG_PERSIST_DIR
BM25_INDEX_PATH = os.getenv("ADMIN_BM25_INDEX_PATH", os.path.join(PERSIST_DIR, "bm25_index.pkl"))
MAX_UPLOAD_BYTES = int(os.getenv("ADMIN_RAG_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
RRF_K = 60
DENSE_CANDIDATES = 20
SPARSE_CANDIDATES = 20
_FAISS_INDEX_FILE = "index.faiss"

_lock = threading.Lock()
_embeddings = None
_vector_store: FAISS | None = None
_documents: list[Document] = []
_bm25: BM25Okapi | None = None


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _create_embeddings():
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        from langchain_community.embeddings import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = _create_embeddings()
    return _embeddings


def _faiss_index_exists() -> bool:
    return os.path.isfile(os.path.join(PERSIST_DIR, _FAISS_INDEX_FILE))


def _load_faiss_index() -> FAISS:
    return FAISS.load_local(
        PERSIST_DIR,
        _get_embeddings(),
        allow_dangerous_deserialization=True,
    )


def _serialize_documents(docs: list[Document]) -> list[dict[str, Any]]:
    return [{"page_content": doc.page_content, "metadata": dict(doc.metadata)} for doc in docs]


def _deserialize_documents(payload: list[Any]) -> list[Document]:
    documents: list[Document] = []
    for item in payload:
        if isinstance(item, Document):
            documents.append(item)
        elif isinstance(item, dict):
            documents.append(
                Document(
                    page_content=str(item.get("page_content", "")),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        else:
            documents.append(Document(page_content=str(item), metadata={}))
    return documents


def _load_bm25_from_disk() -> None:
    """Restore BM25 index and document list from disk if present."""
    global _documents, _bm25
    if not os.path.exists(BM25_INDEX_PATH):
        return
    try:
        with open(BM25_INDEX_PATH, "rb") as handle:
            payload = pickle.load(handle)
        docs = payload.get("documents", [])
        if not docs:
            return
        _documents = _deserialize_documents(docs)
        tokenized = [_tokenize(doc.page_content) for doc in _documents]
        _bm25 = BM25Okapi(tokenized)
        logger.info("Admin RAG BM25 index loaded (%d documents)", len(_documents))
    except Exception as exc:
        logger.warning("Failed to load BM25 index: %s", exc)


def _save_bm25_to_disk() -> None:
    os.makedirs(os.path.dirname(BM25_INDEX_PATH) or PERSIST_DIR, exist_ok=True)
    with open(BM25_INDEX_PATH, "wb") as handle:
        pickle.dump({"documents": _serialize_documents(_documents)}, handle)


def _format_chunk(doc: Document) -> str:
    page = doc.metadata.get("page")
    if page is not None:
        return f"[Page {page}] {doc.page_content}"
    return doc.page_content


def _get_admin_vector_store() -> FAISS | None:
    global _vector_store
    if _vector_store is not None:
        return _vector_store
    if not os.path.isdir(PERSIST_DIR):
        return None
    try:
        if _faiss_index_exists():
            _vector_store = _load_faiss_index()
        else:
            os.makedirs(PERSIST_DIR, exist_ok=True)
            _vector_store = FAISS.from_texts(["init"], _get_embeddings())
            _vector_store.save_local(PERSIST_DIR)
        return _vector_store
    except Exception as exc:
        logger.warning("Admin RAG vector store unavailable: %s", exc)
        return None


def _row_to_document(row: Any) -> str | None:
    if isinstance(row, dict):
        parts = []
        for key, value in row.items():
            if value is None:
                continue
            text = str(value).strip()
            if not text or text.lower() == "nan":
                continue
            label = str(key).replace("_", " ").strip().title()
            parts.append(f"{label}: {text}")
        return ", ".join(parts) if parts else None
    text = str(row).strip()
    return text or None


def _clean_text(text: str) -> str:
    """Collapse excessive whitespace in extracted document text."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def _parse_pdf_documents(file_bytes: bytes, filename: str) -> list[Document]:
    """Extract one Document per PDF page with 1-indexed page metadata."""
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        documents: list[Document] = []
        for page_number, page in enumerate(reader.pages):
            cleaned = _clean_text(page.extract_text() or "")
            if cleaned:
                documents.append(
                    Document(page_content=cleaned, metadata={"page": page_number + 1})
                )
        return documents
    except Exception as exc:
        logger.error("Failed to parse PDF file %s: %s", filename, exc, exc_info=True)
        return []


def _parse_docx_documents(file_bytes: bytes, filename: str) -> list[Document]:
    """Extract DOCX text and split into ~500-char chunks with 50-char overlap."""
    try:
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(file_bytes))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        full_text = _clean_text(" ".join(paragraphs))
        if not full_text:
            return []
        if len(full_text) < 500:
            return [Document(page_content=full_text, metadata={})]

        chunk_size = 500
        overlap = 50
        documents: list[Document] = []
        start = 0
        while start < len(full_text):
            chunk = full_text[start : start + chunk_size].strip()
            if chunk:
                documents.append(Document(page_content=chunk, metadata={}))
            start += chunk_size - overlap
            if start >= len(full_text):
                break
        return documents
    except Exception as exc:
        logger.error("Failed to parse DOCX file %s: %s", filename, exc, exc_info=True)
        return []


def _parse_tabular_documents(file_bytes: bytes, ext: str, filename: str) -> list[Document]:
    """Parse CSV, Excel, or JSON into one document string per row."""
    rows: list[Any] = []
    if ext == "json":
        try:
            raw = json.loads(file_bytes.decode("utf-8-sig"))
            if isinstance(raw, list):
                rows = raw
            elif isinstance(raw, dict):
                rows = raw.get("data") or raw.get("records") or raw.get("rows") or [raw]
            else:
                rows = [raw]
        except Exception as exc:
            logger.error("Failed to parse JSON file %s: %s", filename, exc, exc_info=True)
            return []
    elif ext == "csv":
        try:
            df = pd.read_csv(io.BytesIO(file_bytes))
            rows = df.to_dict(orient="records")
        except Exception as exc:
            logger.error("Failed to parse CSV file %s: %s", filename, exc, exc_info=True)
            return []
    elif ext in ("xlsx", "xls"):
        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
            rows = df.to_dict(orient="records")
        except Exception as exc:
            logger.error("Failed to parse Excel file %s: %s", filename, exc, exc_info=True)
            return []
    else:
        return []

    documents: list[Document] = []
    for row in rows:
        text = _row_to_document(row)
        if text:
            documents.append(Document(page_content=text, metadata={}))
    return documents


def parse_upload_to_documents(file_bytes: bytes, filename: str) -> list[Document]:
    """Parse CSV, Excel, JSON, PDF, or DOCX upload into LangChain Document objects."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    logger.info("Processing admin RAG file: filename=%s, extension=%s", filename, ext)
    if ext in ("json", "csv", "xlsx", "xls"):
        return _parse_tabular_documents(file_bytes, ext, filename)
    if ext == "pdf":
        return _parse_pdf_documents(file_bytes, filename)
    if ext == "docx":
        return _parse_docx_documents(file_bytes, filename)
    logger.warning("Unsupported admin RAG file type: %s", filename)
    return []


def ingest_documents(
    file_bytes: bytes,
    filename: str,
    mode: Literal["replace", "append"] = "replace",
) -> dict[str, Any]:
    """
    Parse an uploaded file and build/update dense (FAISS) + sparse (BM25) indices.

    - `replace`: wipe existing data before ingest (default).
    - `append`: add new documents to the existing index.
    """
    global _vector_store, _documents, _bm25

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError(f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")

    documents = parse_upload_to_documents(file_bytes, filename)
    if not documents:
        raise ValueError("No rows found in the uploaded file.")

    t0 = time.perf_counter()
    try:
        with _lock:
            if mode == "replace":
                # Wipe and rebuild
                if os.path.isdir(PERSIST_DIR):
                    shutil.rmtree(PERSIST_DIR, ignore_errors=True)
                os.makedirs(PERSIST_DIR, exist_ok=True)

                embeddings = _get_embeddings()
                vector_store = FAISS.from_texts(["init"], embeddings)
                vector_store.add_documents(documents)
                vector_store.save_local(PERSIST_DIR)
                _vector_store = vector_store

                _documents = list(documents)
                tokenized = [_tokenize(doc.page_content) for doc in _documents]
                _bm25 = BM25Okapi(tokenized)

            else:  # append
                # Make sure existing data is loaded
                if not _documents:
                    _load_bm25_from_disk()
                store = _get_admin_vector_store()
                if store is None:
                    # No previous index — create one, then add
                    os.makedirs(PERSIST_DIR, exist_ok=True)
                    store = FAISS.from_texts(["init"], _get_embeddings())
                    store.add_documents(documents)
                    store.save_local(PERSIST_DIR)
                    _vector_store = store
                else:
                    store.add_documents(documents)
                    store.save_local(PERSIST_DIR)
                    _vector_store = store

                # Append to in-memory document list and rebuild BM25
                _documents.extend(documents)
                tokenized = [_tokenize(doc.page_content) for doc in _documents]
                _bm25 = BM25Okapi(tokenized)

            _save_bm25_to_disk()

    except Exception:
        logger.error(
            "Admin RAG FAISS indexing failed for %s:\n%s",
            filename,
            traceback.format_exc(),
        )
        raise

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "Admin RAG ingest (mode=%s): %d documents indexed in %.0fms (total=%d)",
        mode,
        len(documents),
        elapsed_ms,
        len(_documents),
    )
    return {
        "status": "success",
        "documents_indexed": len(documents),
        "total_documents": len(_documents),
        "mode": mode,
        "elapsed_ms": round(elapsed_ms),
    }


def _reciprocal_rank_fusion(rankings: list[list[int]], top_k: int) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_idx in enumerate(ranking):
            scores[doc_idx] = scores.get(doc_idx, 0.0) + 1.0 / (RRF_K + rank + 1)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [idx for idx, _ in ordered[:top_k]]


def hybrid_retrieve(query: str, top_k: int = 7) -> list[Document]:
    """
    Hybrid search: top dense (vector) + top sparse (BM25) candidates merged via RRF.
    Returns the top_k Document objects (page_content + metadata, e.g. page number).
    """
    if not _documents:
        _load_bm25_from_disk()

    if not _documents or _bm25 is None:
        logger.warning("Admin RAG hybrid_retrieve: no indexed documents")
        return []

    rankings: list[list[int]] = []

    # Sparse (BM25)
    query_tokens = _tokenize(query)
    if query_tokens:
        bm25_scores = _bm25.get_scores(query_tokens)
        sparse_indices = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )
        sparse_top = [
            i for i in sparse_indices[:SPARSE_CANDIDATES] if bm25_scores[i] > 0
        ]
        if sparse_top:
            rankings.append(sparse_top)

    # Dense (vector)
    store = _get_admin_vector_store()
    if store is not None:
        dense_docs = store.similarity_search(query, k=DENSE_CANDIDATES)
        dense_indices: list[int] = []
        for doc in dense_docs:
            try:
                dense_indices.append(
                    next(
                        i
                        for i, stored in enumerate(_documents)
                        if stored.page_content == doc.page_content
                    )
                )
            except StopIteration:
                continue
        if dense_indices:
            rankings.append(dense_indices)

    if not rankings:
        return []

    merged_indices = _reciprocal_rank_fusion(rankings, top_k=top_k)
    final_chunks = [
        _documents[i] for i in merged_indices if 0 <= i < len(_documents)
    ]

    logger.info(
        f"RAG final chunks (top 7): pages={[doc.metadata.get('page', '?') for doc in final_chunks]}"
    )

    logger.info(
        "Admin RAG hybrid_retrieve: query=%r dense=%d sparse=%d merged=%d",
        query[:80],
        len(rankings[1]) if len(rankings) > 1 else 0,
        len(rankings[0]) if rankings else 0,
        len(final_chunks),
    )
    for i, doc in enumerate(final_chunks):
        logger.info(
            "RAG chunk %d: page=%s, content=%s...",
            i + 1,
            doc.metadata.get("page", "N/A"),
            doc.page_content[:100],
        )
    return final_chunks


def get_rag_index_status() -> dict[str, Any]:
    """Return current admin RAG index status for the dashboard."""
    if not _documents:
        _load_bm25_from_disk()
    return {
        "documents_indexed": len(_documents),
        "collection": "faiss",
        "vector_store_ready": _get_admin_vector_store() is not None,
        "bm25_ready": _bm25 is not None and len(_documents) > 0,
    }


def warmup_admin_rag() -> None:
    """Load persisted BM25 index at startup (vector store loads lazily)."""
    _load_bm25_from_disk()
    if _documents:
        _get_admin_vector_store()