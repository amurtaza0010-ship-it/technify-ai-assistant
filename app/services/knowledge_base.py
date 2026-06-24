"""
RAG vector store for TAIA policy documents.

Embeddings + Chroma are initialized once per process and warmed at app startup.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

# Reduce HuggingFace / sentence-transformers noise before heavy imports
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TQDM_DISABLE", "1")

from langchain_chroma import Chroma

from app.services.perf_timer import RequestTimer

logger = logging.getLogger("taia.knowledge_base")
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)

DB = os.path.join(os.path.dirname(__file__), "..", "..", "data", "vector_store")

_embeddings = None
_chroma_db: Optional[Chroma] = None
_init_lock = threading.Lock()
_warmup_seconds: Optional[float] = None
_process_id: Optional[int] = None


def _create_embeddings():
    """Build a single HuggingFace embedding model for this process."""
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        from langchain_community.embeddings import HuggingFaceEmbeddings

    logger.warning(
        "Vector store cache MISS — loading HuggingFaceEmbeddings(all-MiniLM-L6-v2) pid=%s",
        os.getpid(),
    )
    # Do not pass show_progress_bar in encode_kwargs — newer sentence-transformers
    # and langchain wrappers both set it, causing a duplicate-kwarg TypeError.
    return HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _get_vector_store() -> Optional[Chroma]:
    """Return the process-local singleton Chroma store (lazy init)."""
    global _embeddings, _chroma_db, _process_id
    if not os.path.exists(DB):
        return None

    if _chroma_db is not None:
        logger.debug("Vector store cache HIT pid=%s", os.getpid())
        return _chroma_db

    with _init_lock:
        if _chroma_db is not None:
            logger.debug("Vector store cache HIT (after lock) pid=%s", os.getpid())
            return _chroma_db

        t0 = time.perf_counter()
        _embeddings = _create_embeddings()
        _chroma_db = Chroma(persist_directory=DB, embedding_function=_embeddings)
        _process_id = os.getpid()
        elapsed = time.perf_counter() - t0
        logger.info(
            "Vector store initialized in %.2fs pid=%s path=%s",
            elapsed,
            _process_id,
            os.path.abspath(DB),
        )
    return _chroma_db


def warmup_knowledge_base() -> float:
    """Eager-load embeddings at startup so the first chat request is fast."""
    global _warmup_seconds
    if _warmup_seconds is not None:
        return _warmup_seconds

    t0 = time.perf_counter()
    _get_vector_store()
    _warmup_seconds = time.perf_counter() - t0
    if _chroma_db is not None:
        logger.info("Knowledge base warmup complete in %.2fs pid=%s", _warmup_seconds, os.getpid())
    else:
        logger.warning("Knowledge base warmup skipped — vector store path missing: %s", DB)
    return _warmup_seconds


def is_vector_store_ready() -> bool:
    return _chroma_db is not None


def vector_store_status() -> dict:
    return {
        "ready": is_vector_store_ready(),
        "warmup_seconds": _warmup_seconds,
        "pid": os.getpid(),
        "db_path": os.path.abspath(DB) if os.path.exists(DB) else None,
    }


def query_knowledge_base(query: str, timer: RequestTimer | None = None) -> str:
    t0 = time.perf_counter()
    if timer:
        timer.mark("RAG: resolve vector store")
    db = _get_vector_store()
    if db is None:
        return "Knowledge base not initialized."
    if timer:
        timer.mark("RAG: similarity search")
    docs = db.similarity_search(query, k=3)
    if timer:
        timer.mark("RAG: format documents")
    result = "\n\n".join(d.page_content for d in docs)
    logger.info(
        "RAG similarity_search k=3 → %.0fms (%d chunks)",
        (time.perf_counter() - t0) * 1000,
        len(docs),
    )
    return result


async def query_knowledge_base_async(
    query: str, timer: RequestTimer | None = None
) -> str:
    """Run vector search off the asyncio event loop."""
    import asyncio

    return await asyncio.to_thread(query_knowledge_base, query, timer)
