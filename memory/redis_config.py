"""
TAIA Phase 2 - Redis Persistent Memory
Domain-level settings for how conversational memory is stored in Redis.

This module does NOT define connection parameters (host/port/auth) -
those live in config/redis_config.py. This module defines how the
memory layer *uses* Redis: key naming, TTLs, history limits.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisMemorySettings(BaseSettings):
    """Settings controlling TAIA's conversational memory behaviour.

    Override via .env, e.g.:
        TAIA_MEMORY_SESSION_TTL_SECONDS=259200
        TAIA_MEMORY_MAX_MESSAGES_PER_SESSION=40
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TAIA_MEMORY_",
        extra="ignore",
    )

    KEY_PREFIX: str = Field(
        default="taia:session:",
        description="Prefix applied to every session key stored in Redis",
    )
    SESSION_TTL_SECONDS: int = Field(
        default=60 * 60 * 24 * 3,  # 3 days
        description="How long a session's memory survives with no activity",
    )
    MAX_MESSAGES_PER_SESSION: int = Field(
        default=40,
        description="Max number of messages kept per session (sliding window)",
    )
    SUMMARY_TRIGGER_MESSAGE_COUNT: int = Field(
        default=30,
        description="Once a session crosses this many messages, older turns "
        "can be summarised instead of dropped, to preserve long-context recall",
    )


@lru_cache
def get_redis_memory_settings() -> RedisMemorySettings:
    return RedisMemorySettings()
