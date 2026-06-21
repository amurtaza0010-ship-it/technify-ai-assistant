"""
TAIA Phase 2 - Redis Persistent Memory
Core memory manager: persists conversation turns per session in Redis,
with a sliding window, and exposes a LangChain-compatible interface so
it drops straight into existing LangGraph / LCEL chains used by TAIA.

Requires: redis>=5.0, langchain-core (pip install redis langchain-core)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

import redis.asyncio as aioredis
from redis.exceptions import RedisError
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    messages_from_dict,
    messages_to_dict,
)

from config.redis_config import get_redis_connection_settings
from memory.redis_config import get_redis_memory_settings

logger = logging.getLogger("taia.memory.redis")

_connection_settings = get_redis_connection_settings()
_memory_settings = get_redis_memory_settings()

_pool: Optional[aioredis.ConnectionPool] = None


def _get_pool() -> aioredis.ConnectionPool:
    """Lazily builds a single shared connection pool for the whole app."""
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            _connection_settings.connection_url,
            max_connections=_connection_settings.MAX_CONNECTIONS,
            socket_timeout=_connection_settings.SOCKET_TIMEOUT,
            socket_connect_timeout=_connection_settings.SOCKET_CONNECT_TIMEOUT,
            decode_responses=_connection_settings.DECODE_RESPONSES,
        )
    return _pool


def get_redis_client() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=_get_pool())


class RedisChatMemory(BaseChatMessageHistory):
    """
    Persistent, per-session chat memory backed by Redis.

    - Stores each session's messages as a JSON list under
      `{KEY_PREFIX}{session_id}`.
    - Applies a sliding window (MAX_MESSAGES_PER_SESSION) so a single
      session can't grow unbounded.
    - Falls back to an in-process buffer if Redis is unreachable, so a
      Redis outage degrades chat quality instead of crashing requests.
    - Implements LangChain's BaseChatMessageHistory so it wires directly
      into RunnableWithMessageHistory / LangGraph checkpoints.

    Usage:
        memory = RedisChatMemory(session_id=student_session_id)
        await memory.aadd_user_message("What's my attendance %?")
        await memory.aadd_ai_message("Your attendance is 82%.")
        history = await memory.aget_messages()
    """

    def __init__(self, session_id: str):
        if not session_id:
            raise ValueError("session_id is required for RedisChatMemory")
        self.session_id = session_id
        self._key = f"{_memory_settings.KEY_PREFIX}{session_id}"
        self._fallback_buffer: List[BaseMessage] = []
        self._redis_unavailable = False

    # ---- internal helpers --------------------------------------------

    async def _client(self) -> aioredis.Redis:
        return get_redis_client()

    async def _safe_call(self, coro, default=None):
        """Runs a redis call, falling back gracefully on connection errors."""
        try:
            result = await coro
            self._redis_unavailable = False
            return result
        except RedisError as exc:
            if not self._redis_unavailable:
                logger.warning(
                    "Redis unavailable for session %s, falling back to "
                    "in-memory buffer: %s", self.session_id, exc,
                )
            self._redis_unavailable = True
            return default

    # ---- LangChain BaseChatMessageHistory interface --------------------

    @property
    def messages(self) -> List[BaseMessage]:
        """
        Sync property required by BaseChatMessageHistory. The Redis client
        here is async, so inside TAIA's async FastAPI routes prefer
        `aget_messages()`. This sync path only serves the in-memory
        fallback so older sync LangChain code paths don't break.
        """
        return list(self._fallback_buffer)

    async def aget_messages(self) -> List[BaseMessage]:
        client = await self._client()
        raw = await self._safe_call(client.get(self._key))
        if raw is None:
            return list(self._fallback_buffer)
        try:
            payload = json.loads(raw)
            return messages_from_dict([m["data"] for m in payload])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error(
                "Corrupt memory payload for session %s: %s", self.session_id, exc
            )
            return []

    def add_message(self, message: BaseMessage) -> None:
        """Sync fallback entrypoint - buffers locally only."""
        self._fallback_buffer.append(message)

    async def aadd_message(self, message: BaseMessage) -> None:
        await self._append_and_trim(message)

    async def aadd_messages(self, messages: List[BaseMessage]) -> None:
        for message in messages:
            await self._append_and_trim(message)

    async def aadd_user_message(self, content: str) -> None:
        await self.aadd_message(HumanMessage(content=content))

    async def aadd_ai_message(self, content: str) -> None:
        await self.aadd_message(AIMessage(content=content))

    async def aadd_system_message(self, content: str) -> None:
        await self.aadd_message(SystemMessage(content=content))

    def clear(self) -> None:
        self._fallback_buffer.clear()

    async def aclear(self) -> None:
        client = await self._client()
        await self._safe_call(client.delete(self._key))
        self._fallback_buffer.clear()

    # ---- core persistence ----------------------------------------------

    async def _append_and_trim(self, message: BaseMessage) -> None:
        history = await self.aget_messages()
        history.append(message)

        # Sliding window: keep only the most recent N messages.
        if len(history) > _memory_settings.MAX_MESSAGES_PER_SESSION:
            history = history[-_memory_settings.MAX_MESSAGES_PER_SESSION :]

        payload = json.dumps(messages_to_dict(history), default=str)

        client = await self._client()
        await self._safe_call(
            client.set(self._key, payload, ex=_memory_settings.SESSION_TTL_SECONDS)
        )
        self._fallback_buffer = history

    async def aget_session_metadata(self) -> dict:
        """Small helper for TAIA's session/debug endpoints."""
        client = await self._client()
        ttl = await self._safe_call(client.ttl(self._key), default=-2)
        history = await self.aget_messages()
        return {
            "session_id": self.session_id,
            "message_count": len(history),
            "ttl_seconds_remaining": ttl,
            "redis_available": not self._redis_unavailable,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


async def redis_health_check() -> bool:
    """Used by TAIA's /health endpoint to report Redis status."""
    try:
        client = get_redis_client()
        return bool(await client.ping())
    except RedisError as exc:
        logger.error("Redis health check failed: %s", exc)
        return False
