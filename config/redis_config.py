"""
TAIA Phase 2 - Redis Persistent Memory
Infrastructure-level Redis connection configuration.

Loads connection settings from environment variables (.env) using Pydantic.
This file owns the actual connection parameters (host, port, auth, SSL, pool size).
Domain-specific memory settings (TTL, max messages, key prefixes) live in
memory/redis_config.py and import from here.

Requires: pydantic-settings, redis>=5.0 (pip install pydantic-settings redis)
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisConnectionSettings(BaseSettings):
    """Raw Redis connection settings, pulled from environment variables.

    Set these in your .env (never commit the .env itself):
        REDIS_HOST=localhost
        REDIS_PORT=6379
        REDIS_PASSWORD=
        REDIS_DB=0
        REDIS_SSL=false
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REDIS_",
        extra="ignore",
    )

    HOST: str = Field(default="localhost", description="Redis server host")
    PORT: int = Field(default=6379, description="Redis server port")
    PASSWORD: Optional[str] = Field(default=None, description="Redis AUTH password")
    DB: int = Field(default=0, description="Redis logical DB index")
    SSL: bool = Field(default=False, description="Use TLS connection")
    MAX_CONNECTIONS: int = Field(default=20, description="Connection pool size")
    SOCKET_TIMEOUT: int = Field(default=5, description="Socket timeout in seconds")
    SOCKET_CONNECT_TIMEOUT: int = Field(default=5, description="Connect timeout in seconds")
    DECODE_RESPONSES: bool = Field(default=True, description="Decode byte responses to str")

    @property
    def connection_url(self) -> str:
        """Builds a redis:// or rediss:// connection URL from the settings."""
        scheme = "rediss" if self.SSL else "redis"
        auth = f":{self.PASSWORD}@" if self.PASSWORD else ""
        return f"{scheme}://{auth}{self.HOST}:{self.PORT}/{self.DB}"


@lru_cache
def get_redis_connection_settings() -> RedisConnectionSettings:
    """Cached accessor so settings are parsed from env only once."""
    return RedisConnectionSettings()
