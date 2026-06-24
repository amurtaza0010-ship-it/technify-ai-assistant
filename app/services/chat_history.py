"""
Chat history index and retrieval for TAIA.

Tracks per-user session metadata in Redis (sorted set + hash) and reads
conversation turns from LangChain RedisChatMessageHistory keys.
Falls back to in-memory storage when Redis is unavailable.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.chains import chatbot_chain

logger = logging.getLogger("taia.chat_history")

_USER_INDEX_PREFIX = "taia:history:"
_META_PREFIX = "taia:history:meta:"
_MAX_TITLE_LEN = 60

# In-memory fallback when Redis is down: user_id -> list of session dicts
_fallback_index: dict[str, list[dict[str, Any]]] = {}

_redis_pool = None


def _get_redis_url() -> str:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return redis_url
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    db = os.getenv("REDIS_DB", "0")
    return f"redis://{host}:{port}/{db}"


def _redis_client():
    global _redis_pool
    if _redis_pool is None:
        import redis

        _redis_pool = redis.from_url(
            _get_redis_url(),
            decode_responses=True,
            socket_connect_timeout=2,
            max_connections=20,
        )
    return _redis_pool


def _title_from_message(message: str) -> str:
    text = (message or "").strip().replace("\n", " ")
    if len(text) <= _MAX_TITLE_LEN:
        return text or "New chat"
    return text[: _MAX_TITLE_LEN - 3] + "..."


def register_session(user_id: str, session_id: str, user_message: str) -> None:
    """Record or update a chat session for the sidebar history list."""
    if not user_id or not session_id:
        return

    title = _title_from_message(user_message)
    now = time.time()

    if chatbot_chain._use_redis:
        try:
            client = _redis_client()
            meta_key = f"{_META_PREFIX}{session_id}"
            if not client.exists(meta_key):
                client.hset(
                    meta_key,
                    mapping={
                        "user_id": user_id,
                        "title": title,
                        "created_at": str(now),
                        "updated_at": str(now),
                    },
                )
            else:
                client.hset(meta_key, "updated_at", str(now))

            client.zadd(f"{_USER_INDEX_PREFIX}{user_id}", {session_id: now})
            return
        except Exception as exc:
            logger.warning("chat history register failed (%s); using in-memory index.", exc)

    sessions = _fallback_index.setdefault(user_id, [])
    existing = next((s for s in sessions if s["session_id"] == session_id), None)
    if existing:
        existing["updated_at"] = now
    else:
        sessions.append(
            {
                "session_id": session_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
            }
        )
    sessions.sort(key=lambda s: s["updated_at"], reverse=True)


def list_user_sessions(user_id: str) -> list[dict[str, Any]]:
    """Return session summaries for a user, newest first."""
    if chatbot_chain._use_redis:
        try:
            t0 = time.perf_counter()
            client = _redis_client()
            session_ids = client.zrevrange(f"{_USER_INDEX_PREFIX}{user_id}", 0, -1)
            if not session_ids:
                return []
            pipe = client.pipeline()
            for sid in session_ids:
                pipe.hgetall(f"{_META_PREFIX}{sid}")
            metas = pipe.execute()
            results: list[dict[str, Any]] = []
            for sid, meta in zip(session_ids, metas):
                if not meta:
                    continue
                if meta.get("user_id") != user_id:
                    continue
                results.append(
                    {
                        "session_id": sid,
                        "title": meta.get("title") or "New chat",
                        "timestamp": float(meta.get("updated_at") or meta.get("created_at") or 0),
                    }
                )
            logger.info(
                "list_user_sessions user=%s count=%d → %.0fms",
                user_id,
                len(results),
                (time.perf_counter() - t0) * 1000,
            )
            return results
        except Exception as exc:
            logger.warning("chat history list failed (%s); using in-memory index.", exc)

    sessions = _fallback_index.get(user_id, [])
    return [
        {
            "session_id": s["session_id"],
            "title": s.get("title") or "New chat",
            "timestamp": float(s.get("updated_at") or s.get("created_at") or 0),
        }
        for s in sorted(sessions, key=lambda x: x.get("updated_at", 0), reverse=True)
    ]


def get_session_messages(session_id: str) -> list[dict[str, str]]:
    """Return UI-friendly messages for a session (user/assistant only)."""
    stored = chatbot_chain.get_stored_messages(session_id)
    messages: list[dict[str, str]] = []
    for msg in stored:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": msg.content})
    return messages


def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    """Verify the session is owned by the requesting user."""
    if chatbot_chain._use_redis:
        try:
            client = _redis_client()
            meta = client.hgetall(f"{_META_PREFIX}{session_id}")
            if meta:
                return meta.get("user_id") == user_id
        except Exception:
            pass

    sessions = _fallback_index.get(user_id, [])
    return any(s["session_id"] == session_id for s in sessions)
